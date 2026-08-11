from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.gateway.database import GatewayDatabase
from app.gateway.user_repository import UserRepository


def _now() -> datetime:
    return datetime.now(UTC)


class UserSessionService:
    def __init__(self, database: GatewayDatabase, users: UserRepository, *, ttl_seconds: int = 8 * 60 * 60) -> None:
        self.database = database
        self.users = users
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def login(self, username: str, password: str) -> str | None:
        user = self.users.verify_login(username, password)
        if user is None or user["role"] != "user":
            return None
        token = secrets.token_urlsafe(48)
        now = _now()
        expires = now + timedelta(seconds=self.ttl_seconds)
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (now.isoformat(),),
            )
            connection.execute(
                """INSERT INTO user_sessions
                (session_hash, user_id, role, created_at, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self._token_hash(token),
                    user["id"],
                    user["role"],
                    now.isoformat(),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
        return token

    def authenticate(self, token: str | None) -> dict | None:
        if not token:
            return None
        now = _now().isoformat()
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.session_hash=? AND s.revoked_at IS NULL AND s.expires_at > ?
                AND u.status='active' AND u.role='user'""",
                (self._token_hash(token), now),
            ).fetchone()
        return self.users.get_user(int(row["id"])) if row else None

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE session_hash=?",
                (_now().isoformat(), self._token_hash(token)),
            )

    def revoke_all(self, user_id: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (_now().isoformat(), user_id),
            )


__all__ = ["UserSessionService"]
