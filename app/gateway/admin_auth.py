from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from app.gateway.database import GatewayDatabase


def _now() -> datetime:
    return datetime.now(UTC)


def hash_admin_password(password: str, *, iterations: int = 310_000) -> str:
    if len(password) < 10:
        raise ValueError("管理员密码至少需要 10 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_admin_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class AdminSessionService:
    def __init__(
        self,
        database: GatewayDatabase,
        username: str,
        password_hash: str,
        *,
        ttl_seconds: int = 8 * 60 * 60,
    ) -> None:
        self.database = database
        self.username = username
        self.password_hash = password_hash
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def login(self, username: str, password: str) -> str | None:
        if not hmac.compare_digest(username, self.username) or not verify_admin_password(password, self.password_hash):
            return None
        token = secrets.token_urlsafe(48)
        now = _now()
        expires = now + timedelta(seconds=self.ttl_seconds)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now.isoformat(),))
            connection.execute(
                "INSERT INTO admin_sessions(token_hash, username, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                (self._token_hash(token), username, now.isoformat(), expires.isoformat(), now.isoformat()),
            )
        return token

    def authenticate(self, token: str | None) -> str | None:
        if not token:
            return None
        now = _now().isoformat()
        token_hash = self._token_hash(token)
        # 管理页面会并发请求实例、域名和概览。鉴权热路径必须保持只读，
        # 否则多个 SELECT 后再 UPDATE 的延迟事务会互相争抢 SQLite 写锁。
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT username, expires_at FROM admin_sessions WHERE token_hash = ?", (token_hash,),
            ).fetchone()
            if row is None or row["expires_at"] <= now:
                return None
        return str(row["username"])

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (self._token_hash(token),))
