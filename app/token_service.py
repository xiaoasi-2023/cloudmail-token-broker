from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.cloudmail_client import CloudMailClient
from app.errors import BrokerError


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class TokenSnapshot:
    token: str
    version: str
    created_at: float
    expires_at: float

    def public_data(self) -> dict[str, str]:
        return {
            "token": self.token,
            "version": self.version,
            "expiresAt": _iso(self.expires_at) or "",
        }


class TokenService:
    def __init__(
        self,
        cloudmail_client: CloudMailClient,
        *,
        cache_seconds: int,
        refresh_skew_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cloudmail_client = cloudmail_client
        self.cache_seconds = max(60, int(cache_seconds))
        self.refresh_skew_seconds = max(0, int(refresh_skew_seconds))
        self.clock = clock
        self._snapshot: TokenSnapshot | None = None
        self._refresh_lock = asyncio.Lock()
        self._refresh_count = 0
        self._refresh_failure_count = 0
        self._last_error = ""
        self._last_refresh_at: float | None = None

    @staticmethod
    def version_for(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]

    def _usable(self, snapshot: TokenSnapshot | None, now: float) -> bool:
        return bool(snapshot and now < snapshot.expires_at - self.refresh_skew_seconds)

    async def get_token(self) -> tuple[TokenSnapshot, str]:
        now = self.clock()
        snapshot = self._snapshot
        if self._usable(snapshot, now):
            return snapshot, "cache"

        async with self._refresh_lock:
            now = self.clock()
            snapshot = self._snapshot
            if self._usable(snapshot, now):
                return snapshot, "cache"
            try:
                return await self._fetch_locked(), "refresh"
            except Exception:
                # 接近过期时刷新失败，仍可返回尚未真正过期的旧 Token。
                snapshot = self._snapshot
                if snapshot is not None and now < snapshot.expires_at:
                    return snapshot, "stale"
                raise

    async def refresh(self, reported_version: str) -> tuple[TokenSnapshot, str]:
        clean_version = str(reported_version or "").strip()
        async with self._refresh_lock:
            snapshot = self._snapshot
            if snapshot is not None and clean_version and clean_version != snapshot.version:
                return snapshot, "newer-cache"
            return await self._fetch_locked(), "refresh"

    async def force_refresh(self) -> TokenSnapshot:
        async with self._refresh_lock:
            return await self._fetch_locked()

    async def _fetch_locked(self) -> TokenSnapshot:
        try:
            token = await self.cloudmail_client.fetch_token()
        except Exception as exc:
            self._refresh_failure_count += 1
            # 只有 Broker 自己生成的脱敏错误允许进入状态接口，其他异常只保留类型。
            self._last_error = str(exc)[:300] if isinstance(exc, BrokerError) else type(exc).__name__
            raise
        now = self.clock()
        snapshot = TokenSnapshot(
            token=token,
            version=self.version_for(token),
            created_at=now,
            expires_at=now + self.cache_seconds,
        )
        self._snapshot = snapshot
        self._refresh_count += 1
        self._last_refresh_at = now
        self._last_error = ""
        return snapshot

    def status(self) -> dict[str, Any]:
        snapshot = self._snapshot
        return {
            "cached": snapshot is not None,
            "version": snapshot.version if snapshot else "",
            "createdAt": _iso(snapshot.created_at) if snapshot else None,
            "expiresAt": _iso(snapshot.expires_at) if snapshot else None,
            "refreshCount": self._refresh_count,
            "refreshFailureCount": self._refresh_failure_count,
            "lastRefreshAt": _iso(self._last_refresh_at),
            "lastError": self._last_error,
            "refreshing": self._refresh_lock.locked(),
        }
