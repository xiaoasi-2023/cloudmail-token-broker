from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.business_models import CloudMailInstanceConfig, MailDomainConfig, MailMessage
from app.gateway.database import GatewayDatabase
from app.gateway.gateway_schemas import CreateMailboxRequest
from app.gateway.mailbox_service import MailboxGatewayService
from app.gateway.mailbox_token import MailboxTokenSigner
from app.gateway.public_api import create_gateway_router
from app.gateway.database_business_store import DatabaseGatewayBusinessStore


class PlainCipher:
    def encrypt(self, plaintext: str) -> str:
        return "encrypted:" + plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")


class FakeProvider:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_mailbox(self, address: str, password: str) -> bool:
        self.created.append(address)
        return True

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
    _, store = seed_database(tmp_path / "gateway-api.db")
    provider = FakeProvider()
    service = MailboxGatewayService(
        store,
        FakeRegistry(provider),  # type: ignore[arg-type]
        MailboxTokenSigner("s" * 32),
    )
    app = FastAPI()
    app.include_router(create_gateway_router(service, lambda value: {"name": "test-client" if value == "test-key" else "other-client"} if value in {"test-key", "other-key"} else None))

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
        assert invalid_key.json()["code"] == "CLIENT_KEY_INVALID"
