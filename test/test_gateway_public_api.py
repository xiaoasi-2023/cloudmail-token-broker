from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.gateway.business_models import CloudMailInstanceConfig, MailDomainConfig, MailMessage
from app.gateway.database import GatewayDatabase
from app.gateway.gateway_schemas import CreateMailboxRequest
from app.gateway.mailbox_service import MailboxGatewayService
from app.gateway.mailbox_token import MailboxTokenSigner
from app.gateway.public_api import create_gateway_router
from app.gateway.database_business_store import DatabaseGatewayBusinessStore
from app.gateway.user_api import UserApiContext, create_user_router
from app.gateway.user_auth import UserSessionService
from app.gateway.user_repository import UserRepository


class PlainCipher:
    def encrypt(self, plaintext: str) -> str:
        return "encrypted:" + plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")


class FakeProvider:
    def __init__(self, *, succeed: bool = True) -> None:
        self.created: list[str] = []
        self.succeed = succeed

    async def create_mailbox(self, address: str, password: str) -> bool:
        self.created.append(address)
        return self.succeed

    async def list_messages(self, address: str) -> list[MailMessage]:
        return [MailMessage(subject="Your temporary ChatGPT verification code", text="Enter this temporary verification code to continue: 836215", received_at=datetime.now(UTC))]


class FakeRegistry:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    async def client_for(self, instance: CloudMailInstanceConfig) -> FakeProvider:
        return self.provider


def seed_database(path: Path) -> tuple[GatewayDatabase, DatabaseGatewayBusinessStore]:
    database = GatewayDatabase(path)
    database.initialize()
    cipher = PlainCipher()
    now = datetime.now(UTC).isoformat()
    with database.transaction() as connection:
        result = connection.execute(
            """INSERT INTO cloudmail_instances
            (name, base_url, admin_email, admin_password_encrypted, proxy_url,
             verify_tls, enabled, health_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', 1, 1, 'healthy', ?, ?)
            RETURNING id""",
            ("mail-a", "https://mail.test", "admin@test", cipher.encrypt("secret"), now, now),
        )
        instance_id = int(result.fetchone()["id"])
        connection.execute(
            """INSERT INTO mail_domains
            (instance_id, domain, enabled, weight, status, created_at, updated_at)
            VALUES (?, 'one.test', 1, 100, 'healthy', ?, ?)""",
            (instance_id, now, now),
        )
    return database, DatabaseGatewayBusinessStore(database, cipher)


def test_database_store_maps_instance_domain_mailbox_and_health(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "gateway.db")
    domain = store.list_domains()[0]
    instance = store.get_instance(domain.instance_id)
    assert instance is not None
    assert instance.admin_password == "secret"

    service = MailboxGatewayService(
        store,
        FakeRegistry(FakeProvider()),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    data = __import__("asyncio").run(
        service.create_mailbox(CreateMailboxRequest(domain="one.test"), "sqlite-task")
    )
    assert store.get_mailbox(data.mailbox_id) is not None
    assert store.get_idempotency("sqlite-task") is not None
    with database.read() as connection:
        row = connection.execute("SELECT success_count, status FROM mail_domains WHERE id=?", (domain.id,)).fetchone()
    assert row["success_count"] == 1
    assert row["status"] == "healthy"


def test_public_router_create_and_verification_flow(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "gateway-api.db")
    users = UserRepository(database)
    user = users.create_user(username="api-user", password="api-user-password", initial_points=5)
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    app = FastAPI()
    app.include_router(
        create_gateway_router(
            service,
            lambda value: {
                "name": "test-client" if value == "test-key" else "other-client",
                "user_id": user["id"],
            }
            if value in {"test-key", "other-key"}
            else None,
        )
    )

    with TestClient(app) as client:
        created = client.post(
            "/v1/mailboxes",
            headers={"Idempotency-Key": "api-task-1", "X-API-Key": "test-key"},
            json={"purpose": "openai", "domain": "one.test", "addressPattern": "name_digits_4", "name": "image2api"},
        )
        assert created.status_code == 200
        data = created.json()["data"]
        assert data["address"].endswith("@one.test")
        assert data["address"].startswith("image2api")
        assert "instance" not in data

        code = client.post(
            f"/v1/mailboxes/{data['mailboxId']}/verification-code",
            headers={"Authorization": f"Mailbox {data['mailboxToken']}", "X-API-Key": "test-key"},
            json={"waitSeconds": 0},
        )
        assert code.status_code == 200
        assert code.json()["data"] == {"status": "received", "verificationCode": "836215"}

        status = client.get(
            f"/v1/mailboxes/{data['mailboxId']}",
            headers={"Authorization": f"Mailbox {data['mailboxToken']}", "X-API-Key": "test-key"},
        )
        assert status.status_code == 200
        assert status.json()["data"]["status"] == "active"

        cross_client = client.get(
            f"/v1/mailboxes/{data['mailboxId']}",
            headers={"Authorization": f"Mailbox {data['mailboxToken']}", "X-API-Key": "other-key"},
        )
        assert cross_client.status_code == 403
        assert cross_client.json()["code"] == "MAILBOX_ACCESS_DENIED"

        released = client.delete(
            f"/v1/mailboxes/{data['mailboxId']}",
            headers={"Authorization": f"Mailbox {data['mailboxToken']}", "X-API-Key": "test-key"},
        )
        assert released.status_code == 200
        assert released.json()["data"]["status"] == "released"

        unauthorized = client.post(
            f"/v1/mailboxes/{data['mailboxId']}/verification-code",
            headers={"X-API-Key": "test-key"}, json={"waitSeconds": 0},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "MAILBOX_TOKEN_INVALID"

        oversized_key = client.post(
            "/v1/mailboxes",
            headers={"Idempotency-Key": "x" * 257, "X-API-Key": "test-key"},
            json={"purpose": "openai", "domain": "one.test"},
        )
        assert oversized_key.status_code == 422

        invalid_pattern = client.post(
            "/v1/mailboxes",
            json={"purpose": "openai", "addressPattern": "unsupported"},
        )
        assert invalid_pattern.status_code == 422

        invalid_key = client.post(
            "/v1/mailboxes",
            headers={"X-API-Key": "wrong"},
            json={"purpose": "openai"},
        )
        assert invalid_key.status_code == 401
        assert invalid_key.json()["code"] == "API_KEY_INVALID"


def test_user_mailbox_creation_binds_owner_and_charges_once(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox.db")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE credit_rules SET cost_points=2 WHERE operation='create_mailbox'"
        )
    users = UserRepository(database)
    user = users.create_user(username="alice", password="alice-password-123", initial_points=3)
    api_key = users.create_api_key(user["id"], "shared-client")["api_key"]
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    app = FastAPI()
    app.include_router(create_gateway_router(service, users.authenticate_api_key))

    with TestClient(app) as client:
        headers = {"X-API-Key": api_key, "Idempotency-Key": "user-create-1"}
        first = client.post("/v1/mailboxes", headers=headers, json={"domain": "one.test"})
        second = client.post("/v1/mailboxes", headers=headers, json={"domain": "one.test"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["mailboxId"] == second.json()["data"]["mailboxId"]
    assert len(provider.created) == 1
    mailbox_id = first.json()["data"]["mailboxId"]
    mailbox = store.get_mailbox(mailbox_id)
    assert mailbox is not None
    assert mailbox.owner_user_id == user["id"]
    credits = users.get_credits(user["id"])
    assert credits is not None
    assert credits["balance"] == 1
    assert credits["transactions"][0]["type"] == "consume"
    assert credits["transactions"][0]["status"] == "completed"


def test_user_mailbox_creation_rejects_insufficient_credits(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox-insufficient.db")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE credit_rules SET cost_points=2 WHERE operation='create_mailbox'"
        )
    users = UserRepository(database)
    user = users.create_user(username="poor-user", password="poor-user-password", initial_points=1)
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            service.create_mailbox(
                CreateMailboxRequest(domain="one.test"),
                "insufficient-create-1",
                user_id=user["id"],
            )
        )

    assert getattr(error.value, "code", None) == "INSUFFICIENT_CREDITS"
    assert provider.created == []
    credits = users.get_credits(user["id"])
    assert credits is not None
    assert credits["balance"] == 1


def test_user_mailbox_provider_failure_refunds_precharged_points(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox-refund.db")
    users = UserRepository(database)
    user = users.create_user(username="refund-user", password="refund-password-123", initial_points=3)
    service = MailboxGatewayService(
        store,
        FakeRegistry(FakeProvider(succeed=False)),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            service.create_mailbox(
                CreateMailboxRequest(domain="one.test"),
                "refund-create-1",
                user_id=user["id"],
            )
        )

    assert getattr(error.value, "code", None) == "MAILBOX_CREATE_FAILED"
    credits = users.get_credits(user["id"])
    assert credits is not None
    assert credits["balance"] == 3
    assert [item["type"] for item in credits["transactions"][:2]] == ["refund", "consume"]
    assert credits["transactions"][0]["status"] == "completed"
    assert credits["transactions"][1]["status"] == "reversed"


def test_user_mailbox_queries_are_owner_isolated(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox-isolation.db")
    users = UserRepository(database)
    user_a = users.create_user(username="owner-a", password="owner-a-password", initial_points=2)
    user_b = users.create_user(username="owner-b", password="owner-b-password", initial_points=2)
    key_a = users.create_api_key(user_a["id"], "shared-client")["api_key"]
    key_b = users.create_api_key(user_b["id"], "shared-client")["api_key"]
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    created = asyncio.run(
        service.create_mailbox(
            CreateMailboxRequest(domain="one.test"),
            "owner-a-create-1",
            client_name="shared-client",
            user_id=user_a["id"],
        )
    )
    assert len(users.list_user_mailboxes(user_a["id"])) == 1
    assert users.list_user_mailboxes(user_b["id"]) == []

    app = FastAPI()
    app.include_router(create_gateway_router(service, users.authenticate_api_key))
    with TestClient(app) as client:
        own = client.get(
            f"/v1/mailboxes/{created.mailbox_id}",
            headers={"X-API-Key": key_a, "Authorization": f"Mailbox {created.mailbox_token}"},
        )
        other = client.get(
            f"/v1/mailboxes/{created.mailbox_id}",
            headers={"X-API-Key": key_b, "Authorization": f"Mailbox {created.mailbox_token}"},
        )

    assert own.status_code == 200
    assert other.status_code == 403
    assert other.json()["code"] == "MAILBOX_ACCESS_DENIED"


def test_user_center_batch_creation_is_idempotent_and_charges_each_mailbox(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox-batch.db")
    users = UserRepository(database)
    user = users.create_user(username="batch-user", password="batch-user-password", initial_points=3)
    users.set_user_auth_code(user["id"], "batch-pop-code-123")
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    app = FastAPI()
    app.include_router(
        create_user_router(
            UserApiContext(
                users=users,
                sessions=UserSessionService(database, users),
                cookie_secure=False,
                mailbox_service=service,
            )
        )
    )

    with TestClient(app) as client:
        login = client.post(
            "/user-api/auth/login",
            json={"username": "batch-user", "password": "batch-user-password"},
        )
        assert login.status_code == 200
        headers = {"Idempotency-Key": "batch-task-1"}
        payload = {"count": 3, "purpose": "openai", "domain": "one.test"}
        first = client.post("/user-api/mailboxes/batch", headers=headers, json=payload)
        second = client.post("/user-api/mailboxes/batch", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["succeeded"] == 3
    assert first.json()["data"]["failed"] == 0
    assert [item["mailboxId"] for item in first.json()["data"]["created"]] == [
        item["mailboxId"] for item in second.json()["data"]["created"]
    ]
    assert len(provider.created) == 3
    assert len(users.list_user_mailboxes(user["id"])) == 3
    credits = users.get_credits(user["id"])
    assert credits is not None
    assert credits["balance"] == 0


def test_user_center_batch_creation_requires_pop_auth_code(tmp_path: Path) -> None:
    database, store = seed_database(tmp_path / "user-mailbox-batch-auth.db")
    users = UserRepository(database)
    users.create_user(username="no-pop-code", password="no-pop-code-password", initial_points=3)
    service = MailboxGatewayService(
        store,
        FakeRegistry(FakeProvider()),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    app = FastAPI()
    app.include_router(
        create_user_router(
            UserApiContext(
                users=users,
                sessions=UserSessionService(database, users),
                cookie_secure=False,
                mailbox_service=service,
            )
        )
    )

    with TestClient(app) as client:
        client.post(
            "/user-api/auth/login",
            json={"username": "no-pop-code", "password": "no-pop-code-password"},
        )
        response = client.post("/user-api/mailboxes/batch", json={"count": 2})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "USER_AUTH_CODE_REQUIRED"
