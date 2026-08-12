from __future__ import annotations

import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
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
from app.gateway.pop3_provider import Pop3GatewayProvider
from app.gateway.pop3_server import Pop3Server
from app.gateway.registration import (
    RegistrationEmailSender,
    RegistrationEmailSettings,
    UserRegistrationService,
)
from app.gateway.public_api import create_gateway_router
from app.gateway.database_business_store import DatabaseGatewayBusinessStore
from app.gateway.user_api import UserApiContext, create_user_router
from app.gateway.user_auth import UserSessionService
from app.gateway.user_repository import UserRepository
from app.rate_limit import InMemoryRateLimiter


logger = logging.getLogger("xiaoasi_mail_gateway")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, resolved_settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    rate_limiter = InMemoryRateLimiter()

    gateway_repository: GatewayRepository | None = None
    database: GatewayDatabase | None = None
    gateway_providers: CloudMailProviderRegistry | None = None
    gateway_router = None
    admin_router = None
    user_router = None
    user_repository: UserRepository | None = None
    pop3_server: Pop3Server | None = None

    if resolved_settings.gateway_enabled:
        database = GatewayDatabase(resolved_settings.database_url)
        database.initialize()
        cipher = FernetSecretCipher(resolved_settings.data_encryption_key)
        gateway_repository = GatewayRepository(database, cipher)
        password_hash = resolved_settings.admin_password_hash or hash_admin_password(
            resolved_settings.admin_password
        )
        user_repository = UserRepository(database)
        user_repository.ensure_admin(resolved_settings.admin_username, password_hash)
        user_sessions = UserSessionService(
            database,
            user_repository,
            ttl_seconds=resolved_settings.user_session_ttl_seconds,
        )
        registration_service = None
        if resolved_settings.user_registration_enabled:
            registration_service = UserRegistrationService(
                database,
                user_repository,
                RegistrationEmailSender(
                    RegistrationEmailSettings(
                        host=resolved_settings.smtp_host,
                        port=resolved_settings.smtp_port,
                        username=resolved_settings.smtp_username,
                        password=resolved_settings.smtp_password,
                        sender=resolved_settings.smtp_from or resolved_settings.smtp_username,
                        use_tls=resolved_settings.smtp_tls,
                    )
                ),
                code_secret=resolved_settings.mailbox_session_secret,
                ttl_seconds=resolved_settings.user_registration_code_ttl_seconds,
                cooldown_seconds=resolved_settings.user_registration_code_cooldown_seconds,
            )
        business_store = DatabaseGatewayBusinessStore(database, cipher)
        gateway_providers = CloudMailProviderRegistry()
        gateway_service = MailboxGatewayService(
            business_store,
            gateway_providers,
            MailboxTokenSigner(resolved_settings.mailbox_session_secret),
            mailbox_ttl_seconds=resolved_settings.mailbox_session_ttl_seconds,
        )
        user_router = create_user_router(
            UserApiContext(
                users=user_repository,
                sessions=user_sessions,
                cookie_secure=resolved_settings.admin_cookie_secure,
                registration_enabled=resolved_settings.user_registration_enabled,
                registration=registration_service,
                pop3_public_host=resolved_settings.pop3_public_host,
                pop3_public_port=resolved_settings.pop3_public_port,
                mailbox_service=gateway_service,
            )
        )
        if resolved_settings.pop3_enabled:
            pop3_provider = Pop3GatewayProvider(
                database,
                user_repository,
                business_store,
                gateway_providers,
            )
            pop3_server = Pop3Server(
                pop3_provider.authenticate,
                pop3_provider.resolve_mailbox,
                pop3_provider,
                host=resolved_settings.pop3_bind_host,
                port=resolved_settings.pop3_port,
                max_connections=resolved_settings.pop3_max_connections,
                max_auth_failures=resolved_settings.pop3_max_auth_failures,
                max_messages=resolved_settings.pop3_max_messages,
            )
        gateway_router = create_gateway_router(gateway_service, user_repository.authenticate_api_key)
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
                users=user_repository,
                instance_test_hook=test_instance,
                cookie_secure=resolved_settings.admin_cookie_secure,
            )
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            if pop3_server is not None:
                await pop3_server.start()
                logger.info("pop3_server_started host=%s port=%s", pop3_server.host, pop3_server.port)
            yield
        finally:
            if pop3_server is not None:
                await pop3_server.close()
                logger.info("pop3_server_stopped")
            if gateway_providers is not None:
                await gateway_providers.close()
            if database is not None:
                database.dispose()

    app = FastAPI(
        title="Xiaoasi Mail Gateway",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.gateway_repository = gateway_repository
    app.state.user_repository = user_repository
    app.state.pop3_server = pop3_server

    @app.exception_handler(GatewayBusinessError)
    async def gateway_error_handler(request: Request, exc: GatewayBusinessError):
        request.state.error_code = exc.code
        request.state.error_message = exc.message
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    if gateway_router is not None:
        app.include_router(gateway_router)
    if user_router is not None:
        app.include_router(user_router)
    if admin_router is not None:
        app.include_router(admin_router)

    @app.middleware("http")
    async def gateway_request_logger(request: Request, call_next):
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        if request.method == "POST" and request.url.path == "/admin-api/auth/login":
            api_key = request.headers.get("X-API-Key", "")
            client_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest() if api_key else "missing"
            try:
                rate_limiter.check(
                    f"gateway:admin-login:{client_key}",
                    resolved_settings.admin_login_rate_limit_per_minute,
                )
            except GatewayBusinessError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"code": exc.code, "message": exc.message},
                    headers={"X-Request-ID": request_id},
                )
        is_user_batch_create = (
            request.method == "POST" and request.url.path == "/user-api/mailboxes/batch"
        )
        if resolved_settings.gateway_enabled and (
            request.url.path.startswith("/v1/mailboxes") or is_user_batch_create
        ):
            client_key = request.client.host if request.client else "unknown"
            try:
                if request.method == "POST" and (
                    request.url.path == "/v1/mailboxes" or is_user_batch_create
                ):
                    rate_limiter.check(
                        f"gateway:create:{client_key}",
                        resolved_settings.mailbox_create_rate_limit_per_minute,
                    )
                else:
                    rate_limiter.check(
                        f"gateway:mailbox:{client_key}",
                        resolved_settings.mailbox_poll_rate_limit_per_minute,
                    )
            except GatewayBusinessError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"code": exc.code, "message": exc.message},
                    headers={"X-Request-ID": request_id},
                )
        if (
            resolved_settings.gateway_enabled
            and request.method == "POST"
            and request.url.path in {"/user-api/auth/register-code", "/user-api/auth/register"}
        ):
            client_key = request.client.host if request.client else "unknown"
            try:
                rate_limiter.check(
                    f"gateway:user-registration:{client_key}",
                    resolved_settings.user_registration_rate_limit_per_minute,
                )
            except GatewayBusinessError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"code": exc.code, "message": exc.message},
                    headers={"X-Request-ID": request_id},
                )
        response = await call_next(request)
        if gateway_repository is not None and (
            request.url.path.startswith("/v1/mailboxes") or is_user_batch_create
        ):
            try:
                gateway_repository.log_request(
                    request_id=request_id,
                    endpoint=request.url.path,
                    method=request.method,
                    source=str(getattr(request.state, "client_name", "")),
                    user_id=getattr(request.state, "user_id", None),
                    status_code=response.status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    error_code=str(getattr(request.state, "error_code", "")),
                    error_message=str(getattr(request.state, "error_message", "")),
                )
            except Exception:
                logger.exception("gateway_request_log_failed request_id=%s", request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/healthz")
    async def healthz():
        return {
            "ok": True,
            "service": "xiaoasi-mail-gateway",
            "gatewayEnabled": resolved_settings.gateway_enabled,
            "pop3Enabled": pop3_server is not None,
            "pop3Listening": pop3_server is not None and pop3_server.server is not None,
        }

    @app.get("/")
    async def root():
        if resolved_settings.gateway_enabled:
            return RedirectResponse(url="/user/")
        return {"ok": True, "service": "xiaoasi-mail-gateway", "gatewayEnabled": False}

    static_path = Path(resolved_settings.admin_static_dir)
    if resolved_settings.gateway_enabled and static_path.is_dir():
        app.mount("/admin", StaticFiles(directory=static_path, html=True), name="gateway-admin")
        app.mount("/user", StaticFiles(directory=static_path, html=True), name="gateway-user")

    return app
