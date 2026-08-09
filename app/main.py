from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from app.auth import AuthRegistry, ClientIdentity
from app.cloudmail_client import CloudMailClient
from app.config import Settings
from app.errors import BrokerError
from app.rate_limit import InMemoryRateLimiter
from app.schemas import RefreshRequest, TokenResponse
from app.token_service import TokenService


logger = logging.getLogger("cloudmail_token_broker")


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
    resolved_client = cloudmail_client or CloudMailClient(resolved_settings)
    token_service = TokenService(
        resolved_client,
        cache_seconds=resolved_settings.token_cache_seconds,
        refresh_skew_seconds=resolved_settings.token_refresh_skew_seconds,
    )
    auth = AuthRegistry(resolved_settings.broker_client_keys, resolved_settings.broker_admin_key)
    rate_limiter = InMemoryRateLimiter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await resolved_client.close()

    app = FastAPI(
        title="CloudMail Token Broker",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.token_service = token_service

    @app.exception_handler(BrokerError)
    async def broker_error_handler(_request: Request, exc: BrokerError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    def require_client(authorization: str | None) -> ClientIdentity:
        return auth.require_client(authorization)

    def require_admin(authorization: str | None) -> None:
        auth.require_admin(authorization)

    def token_payload(snapshot) -> dict[str, Any]:
        return {"code": 200, "data": snapshot.public_data()}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "service": "cloudmail-token-broker"}

    @app.post("/v1/token", response_model=TokenResponse)
    async def get_token(authorization: str | None = Header(default=None)):
        identity = require_client(authorization)
        rate_limiter.check(
            f"token:{identity.client_id}",
            resolved_settings.token_rate_limit_per_minute,
        )
        snapshot, source = await token_service.get_token()
        logger.info("token_served client_id=%s version=%s source=%s", identity.client_id, snapshot.version, source)
        return token_payload(snapshot)

    @app.post("/v1/token/refresh", response_model=TokenResponse)
    async def refresh_token(body: RefreshRequest, authorization: str | None = Header(default=None)):
        identity = require_client(authorization)
        rate_limiter.check(
            f"refresh:{identity.client_id}",
            resolved_settings.refresh_rate_limit_per_minute,
        )
        snapshot, source = await token_service.refresh(body.version)
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
        snapshot, source = await token_service.get_token()
        logger.info("compat_token_served client_id=%s version=%s source=%s", identity.client_id, snapshot.version, source)
        return {"code": 200, "data": {"token": snapshot.token}}

    @app.get("/admin/status")
    async def admin_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rate_limiter.check("admin:status", resolved_settings.admin_rate_limit_per_minute * 10)
        return {"ok": True, "service": "cloudmail-token-broker", "token": token_service.status()}

    @app.post("/admin/token/refresh")
    async def admin_refresh(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rate_limiter.check("admin:refresh", resolved_settings.admin_rate_limit_per_minute)
        snapshot = await token_service.force_refresh()
        logger.info("admin_token_refresh version=%s", snapshot.version)
        return {"ok": True, "token": token_service.status()}

    return app
