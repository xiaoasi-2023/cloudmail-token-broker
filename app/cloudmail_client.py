from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.errors import CloudMailTokenError


class CloudMailClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        if client is not None:
            self.client = client
        else:
            kwargs: dict[str, Any] = {
                "timeout": float(settings.request_timeout_seconds),
                "verify": bool(settings.cloudmail_verify_tls),
                "headers": {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "cloudmail-token-broker/0.1.0",
                },
            }
            if settings.cloudmail_proxy:
                kwargs["proxy"] = settings.cloudmail_proxy
            self.client = httpx.AsyncClient(**kwargs)

    async def fetch_token(self) -> str:
        try:
            response = await self.client.post(
                f"{self.settings.cloudmail_base_url}/api/public/genToken",
                json={
                    "email": self.settings.cloudmail_admin_email,
                    "password": self.settings.cloudmail_admin_password,
                },
            )
        except httpx.TimeoutException as exc:
            raise CloudMailTokenError("CloudMail genToken 请求超时") from exc
        except httpx.HTTPError as exc:
            raise CloudMailTokenError("CloudMail genToken 网络请求失败") from exc

        if response.status_code != 200:
            raise CloudMailTokenError(f"CloudMail genToken 返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudMailTokenError("CloudMail genToken 响应不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise CloudMailTokenError("CloudMail genToken 响应结构无效")
        try:
            code = int(payload.get("code"))
        except (TypeError, ValueError):
            code = 0
        if code != 200:
            # 上游 message 可能包含账号、调试参数或其他敏感信息，不向客户端和状态接口回显。
            raise CloudMailTokenError(f"CloudMail genToken 业务状态异常: code={code}")
        data = payload.get("data")
        token = str(data.get("token") or "").strip() if isinstance(data, dict) else ""
        if not token:
            raise CloudMailTokenError("CloudMail genToken 响应缺少 data.token")
        return token

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
