from __future__ import annotations

from fastapi import APIRouter, Header
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


def create_gateway_router(service: MailboxGatewayService) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["mail-gateway"])

    @router.post("/mailboxes", response_model=CreateMailboxResponse)
    async def create_mailbox(
        request: CreateMailboxRequest,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            max_length=256,
        ),
    ) -> CreateMailboxResponse:
        try:
            data = await service.create_mailbox(request, idempotency_key)
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
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> VerificationCodeResponse:
        try:
            token = parse_mailbox_authorization(authorization)
            data = await service.get_verification_code(mailbox_id, token, request)
            return VerificationCodeResponse(data=data)
        except GatewayBusinessError as exc:
            return _error_response(exc)

    @router.get("/mailboxes/{mailbox_id}", response_model=MailboxStatusResponse)
    async def mailbox_status(
        mailbox_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        try:
            token = parse_mailbox_authorization(authorization)
            return MailboxStatusResponse(data=service.get_mailbox_status(mailbox_id, token))
        except GatewayBusinessError as exc:
            return _error_response(exc)

    @router.delete("/mailboxes/{mailbox_id}", response_model=MailboxStatusResponse)
    async def release_mailbox(
        mailbox_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ):
        try:
            token = parse_mailbox_authorization(authorization)
            return MailboxStatusResponse(data=service.release_mailbox(mailbox_id, token))
        except GatewayBusinessError as exc:
            return _error_response(exc)

    return router


def _error_response(exc: GatewayBusinessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )
