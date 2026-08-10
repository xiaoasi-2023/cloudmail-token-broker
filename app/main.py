from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import AuthRegistry, ClientIdentity
from app.cloudmail_client import CloudMailClient
from app.config import Settings
from app.errors import BrokerError
from app.gateway import (
    AdminApiContext,
    AdminSessionService,
    FernetSecretCipher,
    GatewayDatabase,
    GatewayRepository,
    create_admin_router,
    hash_admin_password,
)
from app.gateway.business_errors import GatewayBusinessError
from app.gateway.business_models import CloudMailInstanceConfig
from app.gateway.cloudmail_provider import CloudMailProviderRegistry
from app.gateway.mailbox_service import MailboxGatewayService
from app.gateway.mailbox_token import MailboxTokenSigner
from app.gateway.public_api import create_gateway_router
from app.gateway.sqlite_business_store import SQLiteGatewayBusinessStore
from app.rate_limit import InMemoryRateLimiter
from app.schemas import RefreshRequest, TokenResponse
from app.token_service import TokenService


logger = logging.getLogger("xiaoasi_mail_gateway")


def create_app(
    settings: Settings | None = None,
    *,
    cloudmail_client: CloudMailClient | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, resolved_settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    resolved_client = cloudmail_client
    if resolved_client is None and resolved_settings.legacy_cloudmail_configured:
        resolved_client = CloudMailClient(resolved_settings)
    token_service = (
        TokenService(
            resolved_client,
            cache_seconds=resolved_settings.token_cache_seconds,
            refresh_skew_seconds=resolved_settings.token_refresh_skew_seconds,
        )
        if resolved_client is not None
        else None
    )
    auth = AuthRegistry(resolved_settings.broker_client_keys, resolved_settings.broker_admin_key)
    rate_limiter = InMemoryRateLimiter()

    gateway_repository: GatewayRepository | None = None
    gateway_providers: CloudMailProviderRegistry | None = None
    gateway_router = None
    admin_router = None

    if resolved_settings.gateway_enabled:
        database = GatewayDatabase(resolved_settings.gateway_database_path)
        database.initialize()
        cipher = FernetSecretCipher(resolved_settings.data_encryption_key)
        gateway_repository = GatewayRepository(database, cipher)
        business_store = SQLiteGatewayBusinessStore(database, cipher)
        gateway_providers = CloudMailProviderRegistry()
        gateway_service = MailboxGatewayService(
            business_store,
            gateway_providers,
            MailboxTokenSigner(resolved_settings.mailbox_session_secret),
            mailbox_ttl_seconds=resolved_settings.mailbox_session_ttl_seconds,
        )
        gateway_router = create_gateway_router(gateway_service)
        password_hash = resolved_settings.admin_password_hash or hash_admin_password(
            resolved_settings.admin_password
        )
        sessions = AdminSessionService(
            database,
            resolved_settings.admin_username,
            password_hash,
            ttl_seconds=resolved_settings.admin_session_ttl_seconds,
        )

        async def test_instance(instance: dict[str, Any]) -> dict[str, Any]:
            started = time.perf_counter()
            instance_config = CloudMailInstanceConfig(
                id=int(instance["id"]),
                base_url=str(instance["base_url"]),
                admin_email=str(instance["admin_email"]),
                admin_password=str(instance["admin_password"]),
                proxy_url=str(instance.get("proxy_url") or ""),
                verify_tls=bool(instance.get("verify_tls", True)),
                enabled=bool(instance.get("enabled", True)),
                health_status=str(instance.get("health_status") or "unknown"),
            )
            client = await gateway_providers.client_for(instance_config)
            await client.test_connection()
            return {
                "ok": True,
                "status": "healthy",
                "message": "CloudMail 实例连接成功",
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }

        admin_router = create_admin_router(
            AdminApiContext(
                repository=gateway_repository,
                sessions=sessions,
                instance_test_hook=test_instance,
                cookie_secure=resolved_settings.admin_cookie_secure,
            )
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if resolved_client is not None:
            await resolved_client.close()
        if gateway_providers is not None:
            await gateway_providers.close()

    app = FastAPI(
        title="Xiaoasi Mail Gateway",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.token_service = token_service
    app.state.gateway_repository = gateway_repository

    @app.exception_handler(BrokerError)
    async def broker_error_handler(_request: Request, exc: BrokerError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(GatewayBusinessError)
    async def gateway_error_handler(_request: Request, exc: GatewayBusinessError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    if gateway_router is not None:
        app.include_router(gateway_router)
    if admin_router is not None:
        app.include_router(admin_router)

    @app.middleware("http")
    async def gateway_request_logger(request: Request, call_next):
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        if request.method == "POST" and request.url.path == "/admin-api/auth/login":
            client_key = request.client.host if request.client else "unknown"
            try:
                rate_limiter.check(
                    f"gateway:admin-login:{client_key}",
                    resolved_settings.admin_login_rate_limit_per_minute,
                )
            except BrokerError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"code": exc.code, "message": exc.message},
                    headers={"X-Request-ID": request_id},
                )
        if resolved_settings.gateway_enabled and request.url.path.startswith("/v1/mailboxes"):
            client_key = request.client.host if request.client else "unknown"
            try:
                if request.method == "POST" and request.url.path == "/v1/mailboxes":
                    rate_limiter.check(
                        f"gateway:create:{client_key}",
                        resolved_settings.mailbox_create_rate_limit_per_minute,
                    )
                else:
                    rate_limiter.check(
                        f"gateway:mailbox:{client_key}",
                        resolved_settings.mailbox_poll_rate_limit_per_minute,
                    )
            except BrokerError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"code": exc.code, "message": exc.message},
                    headers={"X-Request-ID": request_id},
                )
        response = await call_next(request)
        if gateway_repository is not None and request.url.path.startswith("/v1/mailboxes"):
            try:
                gateway_repository.log_request(
                    request_id=request_id,
                    endpoint=request.url.path,
                    method=request.method,
                    source=request.headers.get("X-Client-Source", ""),
                    status_code=response.status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
            except Exception:
                logger.exception("gateway_request_log_failed request_id=%s", request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    def require_client(authorization: str | None) -> ClientIdentity:
        if resolved_settings.broker_public_access:
            return ClientIdentity(client_id="public")
        return auth.require_client(authorization)

    def require_admin(authorization: str | None) -> None:
        auth.require_admin(authorization)

    def require_token_service() -> TokenService:
        if token_service is None:
            raise BrokerError("LEGACY_BROKER_DISABLED", "旧 Token Broker 未配置", 503)
        return token_service

    def token_payload(snapshot) -> dict[str, Any]:
        return {"code": 200, "data": snapshot.public_data()}

    @app.get("/healthz")
    async def healthz():
        return {
            "ok": True,
            "service": "xiaoasi-mail-gateway",
            "gatewayEnabled": resolved_settings.gateway_enabled,
        }

    @app.get("/")
    async def root():
        if resolved_settings.gateway_enabled:
            return RedirectResponse(url="/admin/")
        return {"ok": True, "service": "cloudmail-token-broker"}

    @app.post("/v1/token", response_model=TokenResponse)
    async def get_token(authorization: str | None = Header(default=None)):
        identity = require_client(authorization)
        rate_limiter.check(
            f"token:{identity.client_id}",
            resolved_settings.token_rate_limit_per_minute,
        )
        snapshot, source = await require_token_service().get_token()
        logger.info("token_served client_id=%s version=%s source=%s", identity.client_id, snapshot.version, source)
        return token_payload(snapshot)

    @app.post("/v1/token/refresh", response_model=TokenResponse)
    async def refresh_token(body: RefreshRequest, authorization: str | None = Header(default=None)):
        identity = require_client(authorization)
        rate_limiter.check(
            f"refresh:{identity.client_id}",
            resolved_settings.refresh_rate_limit_per_minute,
        )
        snapshot, source = await require_token_service().refresh(body.version)
        logger.info("token_refresh client_id=%s version=%s source=%s", identity.client_id, snapshot.version, source)
        return token_payload(snapshot)

    @app.post("/api/public/genToken")
    async def compatibility_get_token(
        _body: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ):
        identity = require_client(authorization)
        rate_limiter.check(
            f"compat:{identity.client_id}",
            resolved_settings.token_rate_limit_per_minute,
        )
        snapshot, source = await require_token_service().get_token()
        logger.info("compat_token_served client_id=%s version=%s source=%s", identity.client_id, snapshot.version, source)
        return {"code": 200, "data": {"token": snapshot.token}}

    @app.get("/admin/status")
    async def admin_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rate_limiter.check("admin:status", resolved_settings.admin_rate_limit_per_minute * 10)
        service = require_token_service()
        return {"ok": True, "service": "cloudmail-token-broker", "token": service.status()}

    @app.post("/admin/token/refresh")
    async def admin_refresh(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rate_limiter.check("admin:refresh", resolved_settings.admin_rate_limit_per_minute)
        service = require_token_service()
        snapshot = await service.force_refresh()
        logger.info("admin_token_refresh version=%s", snapshot.version)
        return {"ok": True, "token": service.status()}

    static_path = Path(resolved_settings.admin_static_dir)
    if resolved_settings.gateway_enabled and static_path.is_dir():
        app.mount("/admin", StaticFiles(directory=static_path, html=True), name="gateway-admin")

    return app
