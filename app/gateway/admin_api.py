from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.gateway.admin_auth import AdminSessionService
from app.gateway.repository import GatewayRepository


InstanceTestHook = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class AdminApiContext:
    repository: GatewayRepository
    sessions: AdminSessionService
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


def create_admin_router(context: AdminApiContext) -> APIRouter:
    router = APIRouter(prefix="/admin-api", tags=["gateway-admin"])
    cookie_name = "xiaoasi_admin_session"

    def current_admin(session_token: str | None = Cookie(default=None, alias=cookie_name)) -> str:
        username = context.sessions.authenticate(session_token)
        if username is None:
            raise HTTPException(status_code=401, detail={"code": "ADMIN_UNAUTHORIZED", "message": "请先登录管理端"})
        return username

    def not_found(resource: str) -> HTTPException:
        return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"{resource}不存在"})

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
        except sqlite3.IntegrityError as exc:
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
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "INSTANCE_CONFLICT", "message": "实例名称已存在"}) from exc
        if item is None:
            raise not_found("实例")
        context.repository.audit(username, "instance.update", "instance", str(instance_id))
        return {"ok": True, "data": item}

    @router.delete("/instances/{instance_id}")
    async def delete_instance(instance_id: int, username: str = Depends(current_admin)):
        try:
            deleted = context.repository.delete_instance(instance_id)
        except sqlite3.IntegrityError as exc:
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
        except sqlite3.IntegrityError as exc:
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
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "DOMAIN_CONFLICT", "message": "域名已存在或数据无效"}) from exc
        if item is None:
            raise not_found("域名")
        context.repository.audit(username, "domain.update", "domain", str(domain_id))
        return {"ok": True, "data": item}

    @router.delete("/domains/{domain_id}")
    async def delete_domain(domain_id: int, username: str = Depends(current_admin)):
        try:
            deleted = context.repository.delete_domain(domain_id)
        except sqlite3.IntegrityError as exc:
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
        _username: str = Depends(current_admin),
    ):
        return {"ok": True, "data": context.repository.list_mailboxes(limit, offset)}

    @router.get("/request-logs")
    async def list_request_logs(
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
        _username: str = Depends(current_admin),
    ):
        return {"ok": True, "data": context.repository.list_request_logs(limit, offset)}

    return router
