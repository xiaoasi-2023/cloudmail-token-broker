from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.gateway.admin_auth import AdminSessionService
from app.gateway.database import DatabaseIntegrityError
from app.gateway.repository import GatewayRepository
from app.gateway.user_repository import UserRepository


InstanceTestHook = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class AdminApiContext:
    repository: GatewayRepository
    sessions: AdminSessionService
    users: UserRepository | None = None
    instance_test_hook: InstanceTestHook | None = None
    cookie_secure: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


class InstanceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=8, max_length=500)
    admin_email: str = Field(min_length=3, max_length=320)
    admin_password: str = Field(min_length=1, max_length=1000)
    proxy_url: str = Field(default="", max_length=500)
    verify_tls: bool = True
    enabled: bool = True


class InstanceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    admin_email: str | None = Field(default=None, min_length=3, max_length=320)
    admin_password: str | None = Field(default=None, max_length=1000)
    proxy_url: str | None = Field(default=None, max_length=500)
    verify_tls: bool | None = None
    enabled: bool | None = None


class DomainCreateRequest(BaseModel):
    instance_id: int
    domain: str = Field(min_length=3, max_length=253)
    enabled: bool = True
    weight: int = Field(default=100, ge=1, le=10000)
    remark: str = Field(default="", max_length=500)


class DomainUpdateRequest(BaseModel):
    instance_id: int | None = None
    domain: str | None = Field(default=None, min_length=3, max_length=253)
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=10000)
    remark: str | None = Field(default=None, max_length=500)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=1000)
    email: str | None = Field(default=None, max_length=320)
    initial_points: int | None = Field(default=None, ge=0)


class UserUpdateRequest(BaseModel):
    enabled: bool


class CreditAdjustRequest(BaseModel):
    amount: int
    reason: str = Field(min_length=1, max_length=500)


class CreditRuleUpdateRequest(BaseModel):
    cost_points: int = Field(ge=0)
    initial_user_points: int = Field(ge=0)


class CreditPackageCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    points: int = Field(gt=0)
    price: int = Field(default=0, ge=0, validation_alias=AliasChoices("price", "amount"))
    purchase_url: str = Field(
        default="",
        max_length=1000,
        validation_alias=AliasChoices("purchase_url", "purchaseUrl", "purchase_link", "purchaseLink"),
    )
    enabled: bool = True


class CreditPackageUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    points: int | None = Field(default=None, gt=0)
    price: int | None = Field(default=None, ge=0, validation_alias=AliasChoices("price", "amount"))
    purchase_url: str | None = Field(
        default=None,
        max_length=1000,
        validation_alias=AliasChoices("purchase_url", "purchaseUrl", "purchase_link", "purchaseLink"),
    )
    enabled: bool | None = None


class CdkGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    package_id: int = Field(validation_alias=AliasChoices("package_id", "packageId"))
    count: int = Field(default=1, ge=1, le=10000, validation_alias=AliasChoices("count", "quantity"))


class CdkRedeemRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(
        min_length=4,
        max_length=200,
        validation_alias=AliasChoices("code", "cdk", "cdk_code", "cdkCode"),
    )


class PopAuthCodeRequest(BaseModel):
    auth_code: str = Field(min_length=10, max_length=1000)


def create_admin_router(context: AdminApiContext) -> APIRouter:
    router = APIRouter(prefix="/admin-api", tags=["gateway-admin"])
    cookie_name = "xiaoasi_admin_session"
    users = context.users or UserRepository(context.repository.database)
    if context.users is None:
        users.ensure_admin(context.sessions.username, context.sessions.password_hash)

    def current_admin(session_token: str | None = Cookie(default=None, alias=cookie_name)) -> str:
        username = context.sessions.authenticate(session_token)
        if username is None:
            raise HTTPException(status_code=401, detail={"code": "ADMIN_UNAUTHORIZED", "message": "请先登录管理端"})
        return username

    def not_found(resource: str) -> HTTPException:
        return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"{resource}不存在"})

    def current_admin_user(username: str) -> dict[str, Any]:
        user = users.get_user_by_username(username)
        if user is None or user["role"] != "admin" or user["status"] != "active":
            raise HTTPException(status_code=401, detail={"code": "ADMIN_UNAUTHORIZED", "message": "管理员账号无效"})
        return user

    def audit_admin(
        username: str,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: str = "",
        request: Request | None = None,
    ) -> None:
        admin = current_admin_user(username)
        users.audit_admin(
            admin_user_id=admin["id"],
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            request_id=request.headers.get("X-Request-ID", "") if request else "",
            source_ip=request.client.host if request and request.client else "",
        )

    @router.post("/auth/login")
    async def login(body: LoginRequest, response: Response):
        token = context.sessions.login(body.username, body.password)
        if token is None:
            raise HTTPException(status_code=401, detail={"code": "LOGIN_FAILED", "message": "用户名或密码错误"})
        response.set_cookie(
            cookie_name, token, httponly=True, secure=context.cookie_secure,
            samesite="strict", max_age=context.sessions.ttl_seconds, path="/",
        )
        context.repository.audit(body.username, "admin.login")
        return {"ok": True, "username": body.username}

    @router.get("/auth/session")
    async def auth_session(
        session_token: str | None = Cookie(default=None, alias=cookie_name),
    ):
        username = context.sessions.authenticate(session_token)
        return {
            "ok": True,
            "authenticated": username is not None,
            "username": username or "",
        }

    @router.post("/auth/logout")
    async def logout(
        response: Response,
        session_token: str | None = Cookie(default=None, alias=cookie_name),
        username: str = Depends(current_admin),
    ):
        context.sessions.logout(session_token)
        response.delete_cookie(cookie_name, path="/")
        context.repository.audit(username, "admin.logout")
        return {"ok": True}

    @router.get("/users")
    async def list_users(_username: str = Depends(current_admin)):
        return {"ok": True, "data": users.list_users()}

    @router.post("/users", status_code=201)
    async def create_user(
        body: UserCreateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        try:
            item = users.create_user(
                username=body.username,
                password=body.password,
                email=body.email,
                initial_points=body.initial_points,
            )
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "USER_CONFLICT", "message": "用户名或邮箱已存在"}) from exc
        audit_admin(username, "user.create", "user", str(item["id"]), request=request)
        return {"ok": True, "data": item}

    @router.patch("/users/{user_id}")
    async def update_user(
        user_id: int,
        body: UserUpdateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        item = users.set_user_enabled(user_id, body.enabled)
        if item is None:
            raise not_found("普通用户")
        audit_admin(
            username,
            "user.update_status",
            "user",
            str(user_id),
            detail=f"status={'active' if body.enabled else 'disabled'}",
            request=request,
        )
        return {"ok": True, "data": item}

    @router.post("/users/{user_id}/reset-auth-code")
    async def reset_user_auth_code(
        user_id: int,
        request: Request,
        username: str = Depends(current_admin),
    ):
        item = users.clear_user_auth_code(user_id)
        if item is None:
            raise not_found("普通用户")
        audit_admin(username, "user.reset_auth_code", "user", str(user_id), request=request)
        return {"ok": True, "data": {"user_id": user_id, "configured": False}}

    @router.post("/users/{user_id}/credits/adjust")
    async def adjust_user_credits(
        user_id: int,
        body: CreditAdjustRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        admin = current_admin_user(username)
        item = users.adjust_credits(
            user_id=user_id,
            amount=body.amount,
            reason=body.reason,
            admin_user_id=admin["id"],
        )
        if item is None:
            raise HTTPException(status_code=400, detail={"code": "CREDIT_ADJUST_FAILED", "message": users.error})
        audit_admin(
            username,
            "credit.adjust",
            "user",
            str(user_id),
            detail=f"amount={body.amount};balance_after={item['balance_after']};reason={body.reason.strip()}",
            request=request,
        )
        return {"ok": True, "data": item}

    @router.get("/users/{user_id}/credit-transactions")
    async def list_user_credit_transactions(
        user_id: int,
        limit: int = Query(default=100, ge=1, le=500),
        _username: str = Depends(current_admin),
    ):
        if users.get_user(user_id) is None:
            raise not_found("普通用户")
        return {"ok": True, "data": users.list_credit_transactions(user_id, limit)}

    @router.get("/credit-rules")
    async def get_credit_rules(_username: str = Depends(current_admin)):
        return {"ok": True, "data": users.get_credit_rule()}

    @router.put("/credit-rules")
    async def update_credit_rules(
        body: CreditRuleUpdateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        admin = current_admin_user(username)
        item = users.update_credit_rule(
            cost_points=body.cost_points,
            initial_user_points=body.initial_user_points,
            admin_user_id=admin["id"],
        )
        audit_admin(username, "credit_rule.update", "credit_rule", "create_mailbox", request=request)
        return {"ok": True, "data": item}

    @router.get("/credit-packages")
    @router.get("/cdk-packages")
    @router.get("/packages")
    async def list_credit_packages(
        enabled: bool | None = Query(default=None),
        keyword: str = Query(default="", max_length=100),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        _username: str = Depends(current_admin),
    ):
        return {
            "ok": True,
            "data": context.repository.list_credit_packages(
                enabled=enabled, keyword=keyword, limit=limit, offset=offset
            ),
        }

    @router.post("/credit-packages", status_code=201)
    @router.post("/cdk-packages", status_code=201)
    @router.post("/packages", status_code=201)
    async def create_credit_package(
        body: CreditPackageCreateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        try:
            item = context.repository.create_credit_package(body.model_dump())
        except (DatabaseIntegrityError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, DatabaseIntegrityError) else 400,
                detail={"code": "CREDIT_PACKAGE_CREATE_FAILED", "message": str(exc)},
            ) from exc
        audit_admin(username, "credit_package.create", "credit_package", str(item["id"]), request=request)
        return {"ok": True, "data": item}

    @router.get("/credit-packages/{package_id}")
    @router.get("/cdk-packages/{package_id}")
    @router.get("/packages/{package_id}")
    async def get_credit_package(package_id: int, _username: str = Depends(current_admin)):
        item = context.repository.get_credit_package(package_id)
        if item is None:
            raise not_found("积分套餐")
        return {"ok": True, "data": item}

    @router.patch("/credit-packages/{package_id}")
    @router.patch("/cdk-packages/{package_id}")
    @router.patch("/packages/{package_id}")
    async def update_credit_package(
        package_id: int,
        body: CreditPackageUpdateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        try:
            item = context.repository.update_credit_package(
                package_id, body.model_dump(exclude_none=True)
            )
        except (DatabaseIntegrityError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, DatabaseIntegrityError) else 400,
                detail={"code": "CREDIT_PACKAGE_UPDATE_FAILED", "message": str(exc)},
            ) from exc
        if item is None:
            raise not_found("积分套餐")
        audit_admin(username, "credit_package.update", "credit_package", str(package_id), request=request)
        return {"ok": True, "data": item}

    @router.delete("/credit-packages/{package_id}")
    @router.delete("/cdk-packages/{package_id}")
    @router.delete("/packages/{package_id}")
    async def delete_credit_package(
        package_id: int,
        request: Request,
        username: str = Depends(current_admin),
    ):
        try:
            deleted = context.repository.delete_credit_package(package_id)
        except DatabaseIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "CREDIT_PACKAGE_IN_USE", "message": "套餐已有 CDK，不能直接删除"},
            ) from exc
        if not deleted:
            raise not_found("积分套餐")
        audit_admin(username, "credit_package.delete", "credit_package", str(package_id), request=request)
        return {"ok": True}

    @router.post("/credit-packages/{package_id}/disable")
    @router.post("/cdk-packages/{package_id}/disable")
    @router.post("/packages/{package_id}/disable")
    async def disable_credit_package(
        package_id: int,
        request: Request,
        username: str = Depends(current_admin),
    ):
        item = context.repository.disable_credit_package(package_id)
        if item is None:
            raise not_found("积分套餐")
        audit_admin(username, "credit_package.disable", "credit_package", str(package_id), request=request)
        return {"ok": True, "data": item}

    @router.get("/cdks")
    @router.get("/credit-cdks")
    async def list_cdks(
        status: str = Query(default="", max_length=20),
        package_id: int | None = Query(default=None),
        keyword: str = Query(default="", max_length=100),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        _username: str = Depends(current_admin),
    ):
        return {
            "ok": True,
            "data": context.repository.list_cdks(
                status=status,
                package_id=package_id,
                keyword=keyword,
                limit=limit,
                offset=offset,
            ),
        }

    @router.post("/cdks/generate", status_code=201)
    @router.post("/cdks/batch", status_code=201)
    @router.post("/credit-cdks/generate", status_code=201)
    async def generate_cdks(
        body: CdkGenerateRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        admin = current_admin_user(username)
        try:
            items = context.repository.generate_cdks(body.package_id, body.count, int(admin["id"]))
        except ValueError as exc:
            code = str(exc)
            status_code = 404 if code == "PACKAGE_NOT_FOUND" else 409 if code == "PACKAGE_DISABLED" else 400
            raise HTTPException(
                status_code=status_code,
                detail={"code": code, "message": "套餐不存在" if code == "PACKAGE_NOT_FOUND" else "套餐已禁用" if code == "PACKAGE_DISABLED" else code},
            ) from exc
        audit_admin(
            username,
            "cdk.generate",
            "credit_package",
            str(body.package_id),
            detail=f"count={body.count}",
            request=request,
        )
        return {
            "ok": True,
            "data": {
                "package_id": body.package_id,
                "quantity": len(items),
                "items": items,
            },
        }

    @router.patch("/cdks/{cdk_id}/disable")
    @router.post("/cdks/{cdk_id}/disable")
    @router.patch("/credit-cdks/{cdk_id}/disable")
    @router.post("/credit-cdks/{cdk_id}/disable")
    async def disable_cdk(
        cdk_id: int,
        request: Request,
        username: str = Depends(current_admin),
    ):
        admin = current_admin_user(username)
        item = context.repository.disable_cdk(cdk_id, int(admin["id"]))
        if item is None:
            raise not_found("CDK")
        if item["status"] == "redeemed":
            raise HTTPException(status_code=409, detail={"code": "CDK_ALREADY_REDEEMED", "message": "CDK 已兑换"})
        audit_admin(username, "cdk.disable", "cdk", str(cdk_id), request=request)
        return {"ok": True, "data": item}

    @router.get("/pop-auth-code")
    async def get_admin_pop_auth_code(_username: str = Depends(current_admin)):
        return {"ok": True, "data": users.get_admin_pop_auth_code()}

    @router.put("/pop-auth-code")
    async def update_admin_pop_auth_code(
        body: PopAuthCodeRequest,
        request: Request,
        username: str = Depends(current_admin),
    ):
        item = users.set_admin_pop_auth_code(body.auth_code)
        if item is None:
            raise HTTPException(status_code=400, detail={"code": "POP_AUTH_CODE_SET_FAILED", "message": users.error})
        audit_admin(username, "admin.pop_auth_code.update", "admin", str(item["id"]), request=request)
        return {"ok": True, "data": users.get_admin_pop_auth_code()}

    @router.get("/overview")
    async def overview(_username: str = Depends(current_admin)):
        return {"ok": True, "data": context.repository.overview()}

    @router.get("/instances")
    async def list_instances(_username: str = Depends(current_admin)):
        return {"ok": True, "data": context.repository.list_instances()}

    @router.post("/instances", status_code=201)
    async def create_instance(body: InstanceCreateRequest, username: str = Depends(current_admin)):
        try:
            item = context.repository.create_instance(body.model_dump())
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "INSTANCE_CONFLICT", "message": "实例名称已存在"}) from exc
        context.repository.audit(username, "instance.create", "instance", str(item["id"]))
        return {"ok": True, "data": item}

    @router.get("/instances/{instance_id}")
    async def get_instance(instance_id: int, _username: str = Depends(current_admin)):
        item = context.repository.get_instance(instance_id)
        if item is None:
            raise not_found("实例")
        return {"ok": True, "data": item}

    @router.patch("/instances/{instance_id}")
    async def update_instance(instance_id: int, body: InstanceUpdateRequest, username: str = Depends(current_admin)):
        try:
            item = context.repository.update_instance(instance_id, body.model_dump(exclude_none=True))
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "INSTANCE_CONFLICT", "message": "实例名称已存在"}) from exc
        if item is None:
            raise not_found("实例")
        context.repository.audit(username, "instance.update", "instance", str(instance_id))
        return {"ok": True, "data": item}

    @router.delete("/instances/{instance_id}")
    async def delete_instance(instance_id: int, username: str = Depends(current_admin)):
        try:
            deleted = context.repository.delete_instance(instance_id)
        except DatabaseIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "INSTANCE_IN_USE", "message": "实例存在邮箱记录，不能直接删除"},
            ) from exc
        if not deleted:
            raise not_found("实例")
        context.repository.audit(username, "instance.delete", "instance", str(instance_id))
        return {"ok": True}

    @router.post("/instances/{instance_id}/test")
    async def test_instance(instance_id: int, username: str = Depends(current_admin)):
        item = context.repository.get_instance(instance_id, include_password=True)
        if item is None:
            raise not_found("实例")
        if context.instance_test_hook is None:
            raise HTTPException(status_code=501, detail={"code": "TEST_HOOK_DISABLED", "message": "实例测试功能尚未接入"})
        try:
            result = await context.instance_test_hook(item)
            context.repository.set_instance_health(instance_id, "healthy")
        except Exception as exc:
            context.repository.set_instance_health(instance_id, "unhealthy", "实例连接测试失败")
            raise HTTPException(
                status_code=502,
                detail={"code": "INSTANCE_TEST_FAILED", "message": "实例连接测试失败，请查看服务端日志"},
            ) from exc
        context.repository.audit(username, "instance.test", "instance", str(instance_id))
        # 测试钩子可以使用完整凭据，但管理接口只返回明确允许的非敏感字段。
        public_result = {
            key: result[key]
            for key in ("ok", "latency_ms", "message", "status")
            if key in result
        }
        return {"ok": True, "data": public_result}

    @router.get("/domains")
    async def list_domains(instance_id: int | None = None, _username: str = Depends(current_admin)):
        return {"ok": True, "data": context.repository.list_domains(instance_id)}

    @router.post("/domains", status_code=201)
    async def create_domain(body: DomainCreateRequest, username: str = Depends(current_admin)):
        if context.repository.get_instance(body.instance_id) is None:
            raise not_found("所属实例")
        try:
            item = context.repository.create_domain(body.model_dump())
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "DOMAIN_CONFLICT", "message": "域名已存在"}) from exc
        context.repository.audit(username, "domain.create", "domain", str(item["id"]))
        return {"ok": True, "data": item}

    @router.patch("/domains/{domain_id}")
    async def update_domain(domain_id: int, body: DomainUpdateRequest, username: str = Depends(current_admin)):
        data = body.model_dump(exclude_none=True)
        if "instance_id" in data and context.repository.get_instance(data["instance_id"]) is None:
            raise not_found("所属实例")
        try:
            item = context.repository.update_domain(domain_id, data)
        except DatabaseIntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "DOMAIN_CONFLICT", "message": "域名已存在或数据无效"}) from exc
        if item is None:
            raise not_found("域名")
        context.repository.audit(username, "domain.update", "domain", str(domain_id))
        return {"ok": True, "data": item}

    @router.delete("/domains/{domain_id}")
    async def delete_domain(domain_id: int, username: str = Depends(current_admin)):
        try:
            deleted = context.repository.delete_domain(domain_id)
        except DatabaseIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "DOMAIN_IN_USE", "message": "域名存在邮箱记录，不能直接删除"},
            ) from exc
        if not deleted:
            raise not_found("域名")
        context.repository.audit(username, "domain.delete", "domain", str(domain_id))
        return {"ok": True}

    @router.post("/domains/{domain_id}/clear-cooldown")
    async def clear_cooldown(domain_id: int, username: str = Depends(current_admin)):
        item = context.repository.clear_domain_cooldown(domain_id)
        if item is None:
            raise not_found("域名")
        context.repository.audit(username, "domain.clear_cooldown", "domain", str(domain_id))
        return {"ok": True, "data": item}

    @router.get("/mailboxes")
    async def list_mailboxes(
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
        keyword: str = Query(default="", max_length=100),
        purpose: str = Query(default="", max_length=32),
        _username: str = Depends(current_admin),
    ):
        return {
            "ok": True,
            "data": context.repository.list_mailboxes(
                limit,
                offset,
                keyword=keyword,
                purpose=purpose,
            ),
        }

    @router.get("/request-logs")
    async def list_request_logs(
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
        keyword: str = Query(default="", max_length=100),
        status_group: str = Query(default="", max_length=32),
        _username: str = Depends(current_admin),
    ):
        return {
            "ok": True,
            "data": context.repository.list_request_logs(
                limit,
                offset,
                keyword=keyword,
                status_group=status_group,
            ),
        }

    return router
