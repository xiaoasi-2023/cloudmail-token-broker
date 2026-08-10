from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.gateway.business_errors import GatewayBusinessError


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class MailboxTokenSigner:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("MAILBOX_SESSION_SECRET 至少需要 32 字节")
        self._secret = secret.encode("utf-8")

    def issue(self, mailbox_id: str, expires_at_epoch: int) -> str:
        payload = _encode(
            json.dumps(
                {"mailboxId": mailbox_id, "exp": int(expires_at_epoch)},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = _encode(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def verify(self, token: str, expected_mailbox_id: str) -> None:
        try:
            payload, signature = token.split(".", 1)
            expected = _encode(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            claims = json.loads(_decode(payload))
            mailbox_id = str(claims["mailboxId"])
            expires_at = int(claims["exp"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GatewayBusinessError("MAILBOX_TOKEN_INVALID", "邮箱访问凭证无效", 401) from exc
        if mailbox_id != expected_mailbox_id:
            raise GatewayBusinessError("MAILBOX_TOKEN_INVALID", "邮箱访问凭证无效", 401)
        if expires_at <= int(time.time()):
            raise GatewayBusinessError("MAILBOX_SESSION_EXPIRED", "邮箱访问凭证已过期", 401)


def parse_mailbox_authorization(authorization: str | None) -> str:
    if not authorization:
        raise GatewayBusinessError("MAILBOX_TOKEN_INVALID", "缺少邮箱访问凭证", 401)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "mailbox" or not token.strip():
        raise GatewayBusinessError("MAILBOX_TOKEN_INVALID", "邮箱访问凭证格式无效", 401)
    return token.strip()
