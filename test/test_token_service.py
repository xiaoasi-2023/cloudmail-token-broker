from __future__ import annotations

import asyncio

import pytest

from app.token_service import TokenService


class FakeCloudMailClient:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = list(tokens)
        self.calls = 0
        self.error: Exception | None = None

    async def fetch_token(self) -> str:
        self.calls += 1
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        index = min(self.calls - 1, len(self.tokens) - 1)
        return self.tokens[index]


def test_concurrent_first_request_fetches_cloudmail_once() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["token-a"])
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)

        results = await asyncio.gather(*(service.get_token() for _ in range(20)))

        assert client.calls == 1
        assert {result[0].token for result in results} == {"token-a"}
        assert sum(result[1] == "refresh" for result in results) == 1

    asyncio.run(scenario())


def test_cache_hit_does_not_fetch_again() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["token-a", "token-b"])
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)

        first, first_source = await service.get_token()
        second, second_source = await service.get_token()

        assert first.token == second.token == "token-a"
        assert first_source == "refresh"
        assert second_source == "cache"
        assert client.calls == 1

    asyncio.run(scenario())


def test_concurrent_same_version_refreshes_once() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["token-a", "token-b", "token-c"])
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)
        current, _ = await service.get_token()

        results = await asyncio.gather(*(service.refresh(current.version) for _ in range(12)))

        assert client.calls == 2
        assert {result[0].token for result in results} == {"token-b"}
        assert sum(result[1] == "refresh" for result in results) == 1
        assert sum(result[1] == "newer-cache" for result in results) == 11

    asyncio.run(scenario())


def test_old_version_returns_newer_cache_without_fetching() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["token-a", "token-b", "token-c"])
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)
        first, _ = await service.get_token()
        second, _ = await service.refresh(first.version)

        returned, source = await service.refresh(first.version)

        assert returned.token == second.token == "token-b"
        assert source == "newer-cache"
        assert client.calls == 2

    asyncio.run(scenario())


def test_refresh_failure_can_return_unexpired_stale_token() -> None:
    async def scenario() -> None:
        now = [1_000.0]
        client = FakeCloudMailClient(["token-a"])
        service = TokenService(
            client,
            cache_seconds=60,
            refresh_skew_seconds=20,
            clock=lambda: now[0],
        )
        first, _ = await service.get_token()
        now[0] = 1_045.0
        client.error = RuntimeError("上游暂时不可用")

        returned, source = await service.get_token()

        assert returned == first
        assert source == "stale"
        assert client.calls == 2
        assert service.status()["refreshFailureCount"] == 1

    asyncio.run(scenario())


def test_refresh_failure_without_cached_token_is_raised() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["unused"])
        client.error = RuntimeError("上游暂时不可用")
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)

        with pytest.raises(RuntimeError, match="上游暂时不可用"):
            await service.get_token()

    asyncio.run(scenario())


def test_unexpected_error_message_is_not_exposed_by_status() -> None:
    async def scenario() -> None:
        client = FakeCloudMailClient(["unused"])
        client.error = RuntimeError("password=secret-value")
        service = TokenService(client, cache_seconds=600, refresh_skew_seconds=30)

        with pytest.raises(RuntimeError):
            await service.get_token()

        assert service.status()["lastError"] == "RuntimeError"
        assert "secret-value" not in str(service.status())

    asyncio.run(scenario())
