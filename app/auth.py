from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from app.errors import BrokerError


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization_token(value: str | None) -> str:
    clean = str(value or "").strip()
    if clean.lower().startswith("bearer "):
        return clean[7:].strip()
    return clean


@dataclass(frozen=True)
class ClientIdentity:
    client_id: str


class AuthRegistry:
    def __init__(self, client_keys: dict[str, str], admin_key: str) -> None:
        self._client_hashes = {_digest(key): client_id for client_id, key in client_keys.items()}
        self._admin_hash = _digest(admin_key) if admin_key else ""

    def require_client(self, authorization: str | None) -> ClientIdentity:
        token = _authorization_token(authorization)
        token_hash = _digest(token) if token else ""
        for expected_hash, client_id in self._client_hashes.items():
            if token_hash and hmac.compare_digest(token_hash, expected_hash):
                return ClientIdentity(client_id=client_id)
        raise BrokerError("BROKER_UNAUTHORIZED", "Broker Client Key 无效", 401)

    def require_admin(self, authorization: str | None) -> None:
        if not self._admin_hash:
            raise BrokerError("ADMIN_DISABLED", "Broker 管理接口未启用", 403)
        token = _authorization_token(authorization)
        token_hash = _digest(token) if token else ""
        if not token_hash or not hmac.compare_digest(token_hash, self._admin_hash):
            raise BrokerError("BROKER_UNAUTHORIZED", "Broker 管理密钥无效", 401)
