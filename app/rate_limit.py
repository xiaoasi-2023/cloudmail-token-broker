from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.gateway.business_errors import GatewayBusinessError


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, *, window_seconds: int = 60) -> None:
        now = time.monotonic()
        cutoff = now - max(1, int(window_seconds))
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= max(1, int(limit)):
                raise GatewayBusinessError("RATE_LIMITED", "请求过于频繁，请稍后重试", 429)
            events.append(now)
