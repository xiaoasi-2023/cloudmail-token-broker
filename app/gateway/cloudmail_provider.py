from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

from app.gateway.business_errors import ProviderRequestError
from app.gateway.business_models import CloudMailInstanceConfig, MailMessage


class CloudMailInstanceClient:
    """单个 CloudMail 实例的客户端和独立 Token 缓存。"""

    def __init__(
        self,
        instance: CloudMailInstanceConfig,
        *,
        token_cache_seconds: int = 1500,
        timeout_seconds: float = 20,
        client: httpx.AsyncClient | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.instance = instance
        self.token_cache_seconds = token_cache_seconds
        self.now = now
        self._token = ""
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)
        self._token_lock = asyncio.Lock()
        self._owns_client = client is None
        if client is not None:
            self.client = client
        else:
            kwargs: dict[str, Any] = {
                "timeout": timeout_seconds,
                "verify": instance.verify_tls,
                "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            }
            if instance.proxy_url:
                kwargs["proxy"] = instance.proxy_url
            self.client = httpx.AsyncClient(**kwargs)

    async def get_token(
        self,
        *,
        force: bool = False,
        rejected_token: str | None = None,
    ) -> str:
        async with self._token_lock:
            if rejected_token is not None:
                if (
                    self._token
                    and self._token != rejected_token
                    and self.now() < self._token_expires_at
                ):
                    # 其他并发请求已经完成刷新，直接复用新 Token，避免连续 genToken 互相覆盖。
                    return self._token
            elif not force and self._token and self.now() < self._token_expires_at:
                return self._token
            payload = await self._post(
                "/api/public/genToken",
                {"email": self.instance.admin_email, "password": self.instance.admin_password},
                token="",
                operation="获取 Token",
            )
            data = payload.get("data")
            token = str(data.get("token") or "").strip() if isinstance(data, dict) else ""
            if not token:
                raise ProviderRequestError("获取 Token", retryable=False)
            self._token = token
            self._token_expires_at = self.now() + timedelta(seconds=self.token_cache_seconds)
            return token

    async def create_mailbox(self, address: str, password: str) -> bool:
        payload = await self._authenticated_post(
            "/api/public/addUser",
            {"list": [{"email": address, "password": password}]},
            operation="创建邮箱",
        )
        code = _response_code(payload)
        if code == 200:
            return True
        message = _response_message(payload).lower()
        if any(marker in message for marker in ("exist", "already", "已存在", "重复")):
            # 短用户名存在碰撞概率，交由网关重新生成，不能把已有邮箱当成创建成功。
            return False
        raise ProviderRequestError("创建邮箱", retryable=code >= 500)

    async def list_messages(self, address: str, *, size: int = 20) -> list[MailMessage]:
        payload = await self._authenticated_post(
            "/api/public/emailList",
            {"toEmail": address, "timeSort": "desc", "size": size, "num": 1},
            operation="查询邮件",
        )
        if _response_code(payload) != 200:
            raise ProviderRequestError("查询邮件")
        data = payload.get("data")
        if data is None:
            return []
        if isinstance(data, dict):
            for key in ("list", "items", "records", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ProviderRequestError("查询邮件", retryable=False)
        return [_parse_message(item) for item in data if isinstance(item, dict)]

    async def test_connection(self) -> None:
        await self.get_token(force=True)

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _authenticated_post(self, path: str, body: dict[str, Any], *, operation: str) -> dict[str, Any]:
        token = await self.get_token()
        payload = await self._post(path, body, token=token, operation=operation, allow_auth_error=True)
        if _response_code(payload) not in {401, 403}:
            return payload

        refreshed_token = await self.get_token(rejected_token=token)
        payload = await self._post(
            path,
            body,
            token=refreshed_token,
            operation=operation,
            allow_auth_error=True,
        )
        if _response_code(payload) not in {401, 403}:
            return payload
        raise ProviderRequestError(operation)

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        token: str,
        operation: str,
        allow_auth_error: bool = False,
    ) -> dict[str, Any]:
        headers = {"Authorization": token} if token else None
        try:
            response = await self.client.post(f"{self.instance.base_url.rstrip('/')}{path}", json=body, headers=headers)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            raise ProviderRequestError(operation) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderRequestError(operation, retryable=False) from exc
        if not isinstance(payload, dict):
            raise ProviderRequestError(operation, retryable=False)
        if response.status_code in {401, 403} and allow_auth_error:
            payload["code"] = response.status_code
            return payload
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderRequestError(operation, retryable=response.status_code >= 500)
        return payload


class CloudMailProviderRegistry:
    """按实例隔离客户端；实例配置变化时自动替换旧客户端。"""

    def __init__(self, factory: Callable[[CloudMailInstanceConfig], CloudMailInstanceClient] | None = None) -> None:
        self.factory = factory or CloudMailInstanceClient
        self._clients: dict[int, tuple[CloudMailInstanceConfig, CloudMailInstanceClient]] = {}
        self._lock = asyncio.Lock()

    async def client_for(self, instance: CloudMailInstanceConfig) -> CloudMailInstanceClient:
        async with self._lock:
            cached = self._clients.get(instance.id)
            if cached and cached[0] == instance:
                return cached[1]
            if cached:
                await cached[1].close()
            client = self.factory(instance)
            self._clients[instance.id] = (instance, client)
            return client

    async def close(self) -> None:
        async with self._lock:
            clients = [item[1] for item in self._clients.values()]
            self._clients.clear()
        for client in clients:
            await client.close()


def _response_code(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("code"))
    except (TypeError, ValueError):
        return 0


def _response_message(payload: dict[str, Any]) -> str:
    return str(payload.get("message") or payload.get("msg") or "")


def _parse_message(item: dict[str, Any]) -> MailMessage:
    return MailMessage(
        subject=_string(item, "subject", "title"),
        text=_string(
            item,
            "text",
            "textBody",
            "text_body",
            "plain",
            "plainText",
            "bodyText",
            "body_text",
            "body",
        ),
        html=_string(
            item,
            "content",
            "html",
            "htmlContent",
            "htmlBody",
            "html_body",
            "bodyHtml",
            "body_html",
        ),
        code=_string(item, "code", "verificationCode", "verification_code"),
        received_at=_message_time(item),
        raw=item,
    )


def _string(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def _message_time(item: dict[str, Any]) -> datetime | None:
    for key in (
        "time",
        "date",
        "created",
        "createdAt",
        "created_at",
        "createTime",
        "create_time",
        "receivedAt",
        "received_at",
        "receiveTime",
        "receive_time",
        "timestamp",
    ):
        value = item.get(key)
        if isinstance(value, (int, float)):
            stamp = float(value)
            if stamp > 1_000_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, UTC)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            try:
                if text.isdigit():
                    stamp = int(text)
                    if stamp > 1_000_000_000_000:
                        stamp //= 1000
                    return datetime.fromtimestamp(stamp, UTC)
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except (ValueError, OverflowError):
                try:
                    parsed = parsedate_to_datetime(text)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    return parsed.astimezone(UTC)
                except (TypeError, ValueError, OverflowError):
                    continue
    return None
