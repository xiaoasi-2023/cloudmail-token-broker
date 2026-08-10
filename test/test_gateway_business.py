from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.gateway.business_errors import GatewayBusinessError
from app.gateway.business_models import (
    CloudMailInstanceConfig,
    IdempotencyRecord,
    MailDomainConfig,
    MailMessage,
    MailboxRecord,
)
from app.gateway.cloudmail_provider import CloudMailInstanceClient
from app.gateway.domain_router import DomainRouter
from app.gateway.gateway_schemas import CreateMailboxRequest, VerificationCodeRequest
from app.gateway.mailbox_service import MailboxGatewayService
from app.gateway.mailbox_token import MailboxTokenSigner


class MemoryStore:
    def __init__(self) -> None:
        self.instances: dict[int, CloudMailInstanceConfig] = {}
        self.domains: list[MailDomainConfig] = []
        self.mailboxes: dict[str, MailboxRecord] = {}
        self.idempotency: dict[str, IdempotencyRecord] = {}
        self.successes: list[int] = []
        self.failures: list[tuple[int, str]] = []

    def list_domains(self) -> list[MailDomainConfig]:
        return self.domains

    def get_instance(self, instance_id: int) -> CloudMailInstanceConfig | None:
        return self.instances.get(instance_id)

    def get_mailbox(self, mailbox_id: str) -> MailboxRecord | None:
        return self.mailboxes.get(mailbox_id)

    def save_mailbox(self, mailbox: MailboxRecord, idempotency: IdempotencyRecord | None = None) -> None:
        self.mailboxes[mailbox.id] = mailbox
        if idempotency:
            self.idempotency[idempotency.key] = idempotency

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        return self.idempotency.get(key)

    def mark_domain_success(self, domain_id: int) -> None:
        self.successes.append(domain_id)

    def mark_domain_failure(self, domain_id: int, error_code: str) -> None:
        self.failures.append((domain_id, error_code))

    def set_verification_status(self, mailbox_id: str, status: str) -> None:
        self.mailboxes[mailbox_id].verification_status = status


def instance(instance_id: int, base_url: str = "https://mail.test") -> CloudMailInstanceConfig:
    return CloudMailInstanceConfig(
        id=instance_id,
        base_url=base_url,
        admin_email=f"admin-{instance_id}@test",
        admin_password="secret",
    )


def test_domain_router_filters_unavailable_and_honors_exact_domain() -> None:
    store = MemoryStore()
    store.instances = {1: instance(1), 2: instance(2)}
    store.domains = [
        MailDomainConfig(id=1, instance_id=1, domain="one.test", weight=1),
        MailDomainConfig(id=2, instance_id=2, domain="two.test", status="unhealthy"),
    ]
    router = DomainRouter(store, random_value=lambda: 0)
    assert [item[0].domain for item in router.candidates(None, None)] == ["one.test"]
    assert router.candidates("ONE.TEST", None)[0][1].id == 1
    with pytest.raises(GatewayBusinessError) as error:
        router.candidates("two.test", None)
    assert error.value.code == "DOMAIN_UNAVAILABLE"


def test_domain_router_orders_weighted_candidates_without_duplicates() -> None:
    store = MemoryStore()
    store.instances = {1: instance(1), 2: instance(2)}
    store.domains = [
        MailDomainConfig(id=1, instance_id=1, domain="heavy.test", weight=100),
        MailDomainConfig(id=2, instance_id=2, domain="light.test", weight=1),
    ]
    candidates = DomainRouter(store, random_value=lambda: 0.5).candidates(None, None)
    assert [item[0].domain for item in candidates] == ["heavy.test", "light.test"]


def test_mailbox_token_cannot_access_another_mailbox_and_expires() -> None:
    signer = MailboxTokenSigner("s" * 32)
    valid = signer.issue("mbx-a", int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()))
    signer.verify(valid, "mbx-a")
    with pytest.raises(GatewayBusinessError) as wrong_mailbox:
        signer.verify(valid, "mbx-b")
    assert wrong_mailbox.value.code == "MAILBOX_TOKEN_INVALID"
    expired = signer.issue("mbx-a", 1)
    with pytest.raises(GatewayBusinessError) as expired_error:
        signer.verify(expired, "mbx-a")
    assert expired_error.value.code == "MAILBOX_SESSION_EXPIRED"


def test_cloudmail_clients_cache_tokens_per_instance_and_refresh_rejected_token_once() -> None:
    token_calls: dict[str, int] = {"a": 0, "b": 0}
    list_authorizations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        key = "a" if host.startswith("a.") else "b"
        if request.url.path == "/api/public/genToken":
            token_calls[key] += 1
            return httpx.Response(200, json={"code": 200, "data": {"token": f"{key}-{token_calls[key]}"}})
        if request.url.path == "/api/public/emailList":
            authorization = request.headers.get("Authorization", "")
            list_authorizations.append(authorization)
            if authorization == "a-1":
                return httpx.Response(401, json={"code": 401})
            return httpx.Response(200, json={"code": 200, "data": []})
        return httpx.Response(404, json={})

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client_a = CloudMailInstanceClient(instance(1, "https://a.test"), client=http_client)
            client_b = CloudMailInstanceClient(instance(2, "https://b.test"), client=http_client)
            await client_a.list_messages("user@a.test")
            await client_b.list_messages("user@b.test")
            await client_b.list_messages("user@b.test")

    asyncio.run(scenario())
    assert token_calls == {"a": 2, "b": 1}
    assert list_authorizations == ["a-1", "a-2", "b-1", "b-1"]


def test_cloudmail_concurrent_auth_failures_share_one_refreshed_token() -> None:
    token_calls = 0
    list_authorizations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/api/public/genToken":
            token_calls += 1
            return httpx.Response(200, json={"code": 200, "data": {"token": f"token-{token_calls}"}})
        if request.url.path == "/api/public/emailList":
            authorization = request.headers.get("Authorization", "")
            list_authorizations.append(authorization)
            if authorization == "token-1":
                await asyncio.sleep(0.01)
                return httpx.Response(401, json={"code": 401})
            return httpx.Response(200, json={"code": 200, "data": []})
        return httpx.Response(404, json={})

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = CloudMailInstanceClient(instance(1), client=http_client)
            await asyncio.gather(
                client.list_messages("first@one.test"),
                client.list_messages("second@one.test"),
            )

    asyncio.run(scenario())
    assert token_calls == 2
    assert list_authorizations.count("token-1") == 2
    assert list_authorizations.count("token-2") == 2


class FakeProviderClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.messages: list[MailMessage] = []

    async def create_mailbox(self, address: str, password: str) -> None:
        assert password
        await asyncio.sleep(0)
        self.created.append(address)

    async def list_messages(self, address: str) -> list[MailMessage]:
        return self.messages


class FakeProviderRegistry:
    def __init__(self, client: FakeProviderClient) -> None:
        self.client = client

    async def client_for(self, value: CloudMailInstanceConfig) -> FakeProviderClient:
        return self.client


def test_mailbox_service_create_is_idempotent_and_extracts_new_code() -> None:
    store = MemoryStore()
    store.instances = {1: instance(1)}
    store.domains = [MailDomainConfig(id=10, instance_id=1, domain="one.test")]
    client = FakeProviderClient()
    service = MailboxGatewayService(
        store,
        FakeProviderRegistry(client),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )

    async def scenario() -> None:
        request = CreateMailboxRequest(purpose="openai", domain="one.test", prefix="Image 2 API")
        first = await service.create_mailbox(request, "task-1")
        second = await service.create_mailbox(request, "task-1")
        assert first.mailbox_id == second.mailbox_id
        assert first.address.startswith("image2api-")
        assert first.address.endswith("@one.test")
        assert len(client.created) == 1

        mailbox = store.mailboxes[first.mailbox_id]
        client.messages = [
            MailMessage(
                subject="Old security code: 111111",
                received_at=mailbox.created_at - timedelta(minutes=1),
            ),
            MailMessage(
                subject="Your security code is 482913",
                received_at=mailbox.created_at + timedelta(seconds=1),
            ),
        ]
        result = await service.get_verification_code(
            first.mailbox_id,
            first.mailbox_token,
            VerificationCodeRequest(waitSeconds=0),
        )
        assert result.status == "received"
        assert result.verification_code == "482913"
        assert store.mailboxes[first.mailbox_id].verification_status == "received"

    asyncio.run(scenario())


def test_idempotency_key_rejects_different_request() -> None:
    store = MemoryStore()
    store.instances = {1: instance(1)}
    store.domains = [MailDomainConfig(id=10, instance_id=1, domain="one.test")]
    service = MailboxGatewayService(
        store,
        FakeProviderRegistry(FakeProviderClient()),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )

    async def scenario() -> None:
        await service.create_mailbox(CreateMailboxRequest(domain="one.test"), "same-key")
        with pytest.raises(GatewayBusinessError) as error:
            await service.create_mailbox(CreateMailboxRequest(domain="one.test", purpose="grok"), "same-key")
        assert error.value.code == "IDEMPOTENCY_CONFLICT"

    asyncio.run(scenario())


def test_concurrent_same_idempotency_key_creates_only_one_mailbox() -> None:
    store = MemoryStore()
    store.instances = {1: instance(1)}
    store.domains = [MailDomainConfig(id=10, instance_id=1, domain="one.test")]
    client = FakeProviderClient()
    service = MailboxGatewayService(
        store,
        FakeProviderRegistry(client),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )

    async def scenario() -> None:
        request = CreateMailboxRequest(domain="one.test")
        first, second = await asyncio.gather(
            service.create_mailbox(request, "concurrent-key"),
            service.create_mailbox(request, "concurrent-key"),
        )
        assert first.mailbox_id == second.mailbox_id

    asyncio.run(scenario())
    assert len(client.created) == 1
    assert service._idempotency_locks == {}
