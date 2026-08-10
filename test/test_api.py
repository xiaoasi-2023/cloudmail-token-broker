from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.cloudmail_client import CloudMailClient
from app.config import Settings
from app.errors import CloudMailTokenError
from app.main import create_app


class FakeCloudMailClient:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = list(tokens)
        self.calls = 0

    async def fetch_token(self) -> str:
        self.calls += 1
        return self.tokens[min(self.calls - 1, len(self.tokens) - 1)]

    async def close(self) -> None:
        return None


def settings(**overrides) -> Settings:
    values = {
        "cloudmail_base_url": "https://mail.example.com",
        "cloudmail_admin_email": "admin@example.com",
        "cloudmail_admin_password": "cloudmail-password-secret",
        "broker_admin_key": "broker-admin-secret",
        "broker_client_keys": {"image2api": "image2api-secret"},
        "broker_public_access": False,
        "token_cache_seconds": 600,
        "token_refresh_skew_seconds": 30,
        "token_rate_limit_per_minute": 60,
        "refresh_rate_limit_per_minute": 10,
        "admin_rate_limit_per_minute": 2,
    }
    values.update(overrides)
    return Settings(**values)


def build_client(fake: FakeCloudMailClient, **settings_overrides) -> TestClient:
    return TestClient(create_app(settings(**settings_overrides), cloudmail_client=fake))


def test_invalid_client_key_returns_401() -> None:
    fake = FakeCloudMailClient(["cloudmail-token-secret"])
    with build_client(fake) as client:
        response = client.post("/v1/token", headers={"Authorization": "Bearer wrong-key"})

    assert response.status_code == 401
    assert response.json()["code"] == "BROKER_UNAUTHORIZED"
    assert fake.calls == 0


def test_public_access_allows_token_without_authorization() -> None:
    fake = FakeCloudMailClient(["cloudmail-token-secret"])
    with build_client(
        fake,
        broker_public_access=True,
        broker_admin_key="",
        broker_client_keys={},
    ) as client:
        token_response = client.post("/v1/token")
        compat_response = client.post("/api/public/genToken", json={})

    assert token_response.status_code == 200
    assert token_response.json()["data"]["token"] == "cloudmail-token-secret"
    assert compat_response.status_code == 200
    assert compat_response.json() == {"code": 200, "data": {"token": "cloudmail-token-secret"}}
    assert fake.calls == 1


def test_public_access_allows_refresh_without_authorization() -> None:
    fake = FakeCloudMailClient(["token-a", "token-b"])
    with build_client(
        fake,
        broker_public_access=True,
        broker_admin_key="",
        broker_client_keys={},
    ) as client:
        first = client.post("/v1/token").json()["data"]
        refreshed = client.post(
            "/v1/token/refresh",
            json={"version": first["version"]},
        )

    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["token"] == "token-b"
    assert fake.calls == 2


def test_admin_endpoint_is_disabled_when_admin_key_is_empty() -> None:
    fake = FakeCloudMailClient(["cloudmail-token-secret"])
    with build_client(
        fake,
        broker_public_access=True,
        broker_admin_key="",
        broker_client_keys={},
    ) as client:
        response = client.get("/admin/status")

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_DISABLED"


def test_token_and_compatibility_endpoints_share_cache() -> None:
    fake = FakeCloudMailClient(["cloudmail-token-secret"])
    headers = {"Authorization": "Bearer image2api-secret"}
    with build_client(fake) as client:
        token_response = client.post("/v1/token", headers=headers, json={})
        compat_response = client.post("/api/public/genToken", headers=headers, json={})

    assert token_response.status_code == 200
    assert token_response.json()["data"]["token"] == "cloudmail-token-secret"
    assert token_response.json()["data"]["version"]
    assert compat_response.status_code == 200
    assert compat_response.json() == {"code": 200, "data": {"token": "cloudmail-token-secret"}}
    assert fake.calls == 1


def test_refresh_with_old_version_returns_current_token() -> None:
    fake = FakeCloudMailClient(["token-a", "token-b", "token-c"])
    headers = {"Authorization": "image2api-secret"}
    with build_client(fake) as client:
        first = client.post("/v1/token", headers=headers).json()["data"]
        second = client.post("/v1/token/refresh", headers=headers, json={"version": first["version"]}).json()["data"]
        third = client.post("/v1/token/refresh", headers=headers, json={"version": first["version"]}).json()["data"]

    assert second["token"] == third["token"] == "token-b"
    assert fake.calls == 2


def test_admin_status_does_not_return_token_or_credentials() -> None:
    fake = FakeCloudMailClient(["cloudmail-token-secret"])
    with build_client(fake) as client:
        client.post("/v1/token", headers={"Authorization": "image2api-secret"})
        response = client.get("/admin/status", headers={"Authorization": "Bearer broker-admin-secret"})

    body = response.json()
    serialized = response.text
    assert response.status_code == 200
    assert body["token"]["cached"] is True
    assert body["token"]["version"]
    assert "cloudmail-token-secret" not in serialized
    assert "cloudmail-password-secret" not in serialized
    assert "image2api-secret" not in serialized
    assert "broker-admin-secret" not in serialized


def test_token_rate_limit_returns_429() -> None:
    fake = FakeCloudMailClient(["token-a"])
    headers = {"Authorization": "Bearer image2api-secret"}
    with build_client(fake, token_rate_limit_per_minute=1) as client:
        first = client.post("/v1/token", headers=headers)
        second = client.post("/v1/token", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_cloudmail_business_error_does_not_echo_upstream_message() -> None:
    secret_message = "password=top-secret token=private-token"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 401, "message": secret_message})

    async def scenario() -> str:
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cloudmail = CloudMailClient(settings(), client=async_client)
        try:
            await cloudmail.fetch_token()
        except CloudMailTokenError as exc:
            return str(exc)
        finally:
            await async_client.aclose()
        raise AssertionError("预期 CloudMailTokenError")

    message = asyncio.run(scenario())

    assert "code=401" in message
    assert secret_message not in message
    assert "top-secret" not in message
