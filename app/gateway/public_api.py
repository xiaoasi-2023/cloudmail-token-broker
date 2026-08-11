from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.gateway.business_errors import GatewayBusinessError
from app.gateway.gateway_schemas import (
    CreateMailboxRequest,
    CreateMailboxResponse,
    MailboxStatusResponse,
    VerificationCodeRequest,
    VerificationCodeResponse,
)
from app.gateway.mailbox_service import MailboxGatewayService
from app.gateway.mailbox_token import parse_mailbox_authorization


UserApiKeyAuthenticator = Callable[[str], dict[str, Any] | None]


def create_gateway_router(
    service: MailboxGatewayService,
    authenticate_user_api_key: UserApiKeyAuthenticator,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["mail-gateway"])

    def authenticated_client(request: Request, api_key: str | None) -> dict[str, Any]:
        client = authenticate_user_api_key(api_key or "")
        if client is None:
            raise GatewayBusinessError("API_KEY_INVALID", "用户调用密钥无效或已停用", 401)
        request.state.client_name = str(client["name"])
        request.state.user_id = int(client["user_id"])
        return client

    @router.post("/mailboxes", response_model=CreateMailboxResponse)
    async def create_mailbox(
        request: CreateMailboxRequest,
        http_request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            max_length=256,
        ),
    ) -> CreateMailboxResponse:
        try:
            client = authenticated_client(http_request, x_api_key)
            data = await service.create_mailbox(
                request,
                idempotency_key,
                str(client["name"]),
                user_id=int(client["user_id"]),
            )
            return CreateMailboxResponse(data=data)
        except GatewayBusinessError as exc:
            return _error_response(exc)

    @router.post(
        "/mailboxes/{mailbox_id}/verification-code",
        response_model=VerificationCodeResponse,
    )
    async def verification_code(
        mailbox_id: str,
        request: VerificationCodeRequest,
        http_request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> VerificationCodeResponse:
        try:
            token = parse_mailbox_authorization(authorization)
            client = authenticated_client(http_request, x_api_key)
            data = await service.get_verification_code(
                mailbox_id,
                token,
                request,
                str(client["name"]),
                user_id=int(client["user_id"]),
            )
            return VerificationCodeResponse(data=data)
        except GatewayBusinessError as exc:
            return _error_response(exc)

    @router.get("/mailboxes/{mailbox_id}", response_model=MailboxStatusResponse)
    async def mailbox_status(
        mailbox_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        try:
            token = parse_mailbox_authorization(authorization)
            client = authenticated_client(request, x_api_key)
            return MailboxStatusResponse(
                data=service.get_mailbox_status(
                    mailbox_id,
                    token,
                    str(client["name"]),
                    user_id=int(client["user_id"]),
                )
            )
        except GatewayBusinessError as exc:
            return _error_response(exc)

    @router.delete("/mailboxes/{mailbox_id}", response_model=MailboxStatusResponse)
    async def release_mailbox(
        mailbox_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        try:
            token = parse_mailbox_authorization(authorization)
            client = authenticated_client(request, x_api_key)
            return MailboxStatusResponse(
                data=service.release_mailbox(
                    mailbox_id,
                    token,
                    str(client["name"]),
                    user_id=int(client["user_id"]),
                )
            )
        except GatewayBusinessError as exc:
            return _error_response(exc)

    return router


def _error_response(exc: GatewayBusinessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )
