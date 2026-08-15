from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.gateway.database import DatabaseIntegrityError
from app.gateway.gateway_schemas import CreateMailboxRequest
from app.gateway.registration import UserRegistrationError, UserRegistrationService
from app.gateway.user_auth import UserSessionService
from app.gateway.user_repository import UserRepository

if TYPE_CHECKING:
    from app.gateway.mailbox_service import MailboxGatewayService


@dataclass(slots=True)
class UserApiContext:
    users: UserRepository
    sessions: UserSessionService
    cookie_secure: bool = True
    registration_enabled: bool = False
    registration: UserRegistrationService | None = None
    pop3_public_host: str = "pop.cloudmail.xiaoasi.xyz"
    pop3_public_port: int = 18110
    mailbox_service: MailboxGatewayService | None = None


class UserLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1000)


class UserPasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("current_password", "currentPassword"),
    )
    new_password: str = Field(
        min_length=10,
        max_length=1000,
        validation_alias=AliasChoices("new_password", "newPassword"),
    )


class UserApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UserAuthCodeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    auth_code: str = Field(
        min_length=10,
        max_length=1000,
        validation_alias=AliasChoices("auth_code", "authCode", "userAuthCode"),
    )


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=1000)
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class UserRegisterCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class BatchCreateMailboxesRequest(CreateMailboxRequest):
    count: int = Field(default=1, ge=1, le=50)


class CdkRedeemRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(
        min_length=4,
        max_length=200,
        validation_alias=AliasChoices("code", "cdk", "cdk_code", "cdkCode"),
    )


def create_user_router(context: UserApiContext) -> APIRouter:
    router = APIRouter(prefix="/user-api", tags=["user-center"])
    cookie_name = "xiaoasi_user_session"

    def current_user(session_token: str | None = Cookie(default=None, alias=cookie_name)) -> dict[str, Any]:
        user = context.sessions.authenticate(session_token)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "USER_UNAUTHORIZED", "message": "请先登录用户中心"},
            )
        return user

    def not_found(resource: str) -> HTTPException:
        return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"{resource}不存在"})

    def auth_code_data(user_id: int) -> dict[str, Any]:
        data = context.users.get_user_pop_auth_code(user_id)
        mailboxes = context.users.list_user_mailboxes(
            user_id,
            limit=500,
        )
        return {
            **data,
            "pop_host": context.pop3_public_host,
            "pop_port": context.pop3_public_port,
            "mailboxes": [
                str(item["address"])
                for item in mailboxes
                if item.get("address")
                and bool(item.get("pop_enabled"))
                and str(item.get("status") or "").strip().lower() in {"active", "expired"}
            ],
        }

    @router.post("/auth/login")
    async def login(body: UserLoginRequest, response: Response):
        token = context.sessions.login(body.username, body.password)
        if token is None:
            raise HTTPException(status_code=401, detail={"code": "LOGIN_FAILED", "message": "用户名或密码错误"})
        user = context.users.get_user_by_username(body.username)
        response.set_cookie(
            cookie_name,
            token,
            httponly=True,
            secure=context.cookie_secure,
            samesite="strict",
            max_age=context.sessions.ttl_seconds,
            path="/",
        )
        return {"ok": True, "data": user}

    @router.get("/auth/registration-config")
    async def registration_config():
        return {
            "ok": True,
            "data": {
                "enabled": context.registration_enabled and context.registration is not None,
                "code_ttl_seconds": context.registration.ttl_seconds if context.registration else 0,
                "code_cooldown_seconds": context.registration.cooldown_seconds if context.registration else 0,
            },
        }

    @router.post("/auth/register-code")
    async def send_register_code(body: UserRegisterCodeRequest):
        if not context.registration_enabled or context.registration is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "USER_REGISTRATION_DISABLED", "message": "用户注册功能已关闭"},
            )
        try:
            data = await run_in_threadpool(context.registration.send_code, body.email)
        except UserRegistrationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return {"ok": True, "data": data}

    @router.post("/auth/logout")
    async def logout(
        response: Response,
        session_token: str | None = Cookie(default=None, alias=cookie_name),
        _user: dict[str, Any] = Depends(current_user),
    ):
        context.sessions.logout(session_token)
        response.delete_cookie(cookie_name, path="/")
        return {"ok": True}

    @router.put("/auth/password")
    async def change_password(
        body: UserPasswordRequest,
        response: Response,
        session_token: str | None = Cookie(default=None, alias=cookie_name),
        user: dict[str, Any] = Depends(current_user),
    ):
        if not context.users.change_password(user["id"], body.current_password, body.new_password):
            raise HTTPException(status_code=400, detail={"code": "PASSWORD_CHANGE_FAILED", "message": context.users.error})
        response.delete_cookie(cookie_name, path="/")
        return {"ok": True}

    @router.post("/auth/sessions/revoke-all")
    async def revoke_all_sessions(user: dict[str, Any] = Depends(current_user)):
        context.sessions.revoke_all(user["id"])
        return {"ok": True}

    @router.get("/me")
    async def me(user: dict[str, Any] = Depends(current_user)):
        return {"ok": True, "data": user}

    @router.get("/api-keys")
    async def list_api_keys(user: dict[str, Any] = Depends(current_user)):
        return {"ok": True, "data": context.users.list_api_keys(user["id"])}

    @router.post("/api-keys", status_code=201)
    async def create_api_key(body: UserApiKeyCreateRequest, user: dict[str, Any] = Depends(current_user)):
        try:
            item = context.users.create_api_key(user["id"], body.name)
        except (DatabaseIntegrityError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "API_KEY_CREATE_FAILED", "message": str(exc)}) from exc
        return {"ok": True, "data": item}

    @router.delete("/api-keys/{key_id}")
    async def revoke_api_key(key_id: int, user: dict[str, Any] = Depends(current_user)):
        if not context.users.revoke_api_key(user["id"], key_id):
            raise not_found("调用密钥")
        return {"ok": True}

    @router.post("/api-keys/{key_id}/regenerate")
    async def regenerate_api_key(key_id: int, user: dict[str, Any] = Depends(current_user)):
        item = context.users.regenerate_api_key(user["id"], key_id)
        if item is None:
            raise not_found("调用密钥")
        return {"ok": True, "data": item}

    @router.put("/auth-code")
    async def set_auth_code(body: UserAuthCodeRequest, user: dict[str, Any] = Depends(current_user)):
        item = context.users.set_user_auth_code(user["id"], body.auth_code)
        if item is None:
            raise HTTPException(status_code=400, detail={"code": "AUTH_CODE_SET_FAILED", "message": context.users.error})
        return {"ok": True, "data": auth_code_data(user["id"])}

    @router.get("/auth-code")
    async def get_auth_code(user: dict[str, Any] = Depends(current_user)):
        return {"ok": True, "data": auth_code_data(user["id"])}

    @router.get("/credits")
    async def credits(
        limit: int = Query(default=20, ge=1, le=100),
        user: dict[str, Any] = Depends(current_user),
    ):
        item = context.users.get_credits(user["id"], limit)
        if item is None:
            raise not_found("用户")
        return {"ok": True, "data": item}

    @router.get("/credits/packages")
    @router.get("/credit-packages")
    async def credit_packages(user: dict[str, Any] = Depends(current_user)):
        del user
        return {"ok": True, "data": context.users.list_credit_packages()}

    @router.post("/credits/redeem")
    @router.post("/credits/redeem-cdk")
    @router.post("/cdks/redeem")
    @router.post("/redeem-cdk")
    async def redeem_cdk(body: CdkRedeemRequest, user: dict[str, Any] = Depends(current_user)):
        try:
            item = context.users.redeem_cdk(int(user["id"]), body.code)
        except ValueError as exc:
            code = str(exc)
            messages = {
                "CDK_INVALID": "CDK 无效",
                "CDK_NOT_FOUND": "CDK 不存在",
                "CDK_DISABLED": "CDK 已禁用",
                "CDK_ALREADY_REDEEMED": "CDK 已被兑换",
                "CDK_UNAVAILABLE": "CDK 当前不可兑换",
                "USER_UNAVAILABLE": "用户账号不可用",
            }
            status_code = 409 if code in {"CDK_DISABLED", "CDK_ALREADY_REDEEMED", "CDK_UNAVAILABLE"} else 400
            raise HTTPException(
                status_code=status_code,
                detail={"code": code, "message": messages.get(code, code)},
            ) from exc
        return {"ok": True, "data": item}

    @router.get("/mailboxes")
    async def mailboxes(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        keyword: str = Query(default="", max_length=100),
        purpose: str = Query(default="", max_length=32),
        status: str = Query(default="", max_length=32),
        verification_status: str = Query(default="", max_length=32),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "data": context.users.list_user_mailboxes(
                user["id"],
                limit,
                offset,
                keyword=keyword,
                purpose=purpose,
                status=status,
                verification_status=verification_status,
            ),
        }

    @router.post("/mailboxes/batch")
    async def create_mailboxes_batch(
        body: BatchCreateMailboxesRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=256),
        user: dict[str, Any] = Depends(current_user),
    ):
        if context.mailbox_service is None:
            raise HTTPException(status_code=503, detail={"code": "MAILBOX_SERVICE_UNAVAILABLE", "message": "邮箱服务当前不可用"})
        auth_code = context.users.get_user_pop_auth_code(int(user["id"]))
        if not auth_code.get("configured"):
            raise HTTPException(status_code=409, detail={"code": "USER_AUTH_CODE_REQUIRED", "message": "请先生成用户级 POP 授权码"})
        batch_key = str(idempotency_key or f"user-{user['id']}-{uuid.uuid4().hex}").strip()
        if not batch_key:
            batch_key = f"user-{user['id']}-{uuid.uuid4().hex}"
        request.state.client_name = "user-center-batch"
        request.state.user_id = int(user["id"])
        request_data = CreateMailboxRequest.model_validate(body.model_dump(exclude={"count"}))
        result = await context.mailbox_service.create_mailboxes(
            request_data,
            body.count,
            idempotency_prefix=f"batch:{batch_key}",
            client_name="user-center-batch",
            user_id=int(user["id"]),
        )
        return {
            "ok": True,
            "data": {
                **result,
                "created": [item.model_dump(by_alias=True) for item in result["created"]],
            },
        }

    @router.post("/auth/register", status_code=201)
    async def register(body: UserRegisterRequest):
        if not context.registration_enabled or context.registration is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "USER_REGISTRATION_DISABLED", "message": "用户注册功能已关闭"},
            )
        try:
            user = await run_in_threadpool(
                context.registration.register,
                username=body.username,
                password=body.password,
                email=body.email,
                code=body.code,
            )
        except UserRegistrationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "USER_CONFLICT", "message": "用户名或邮箱已存在"}) from exc
        return {"ok": True, "data": user}

    return router


__all__ = ["UserApiContext", "create_user_router"]
