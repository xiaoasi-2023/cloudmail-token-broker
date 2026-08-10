from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.database import GatewayDatabase, SCHEMA_VERSION
from app.main import create_app


def gateway_settings(tmp_path: Path) -> Settings:
    return Settings(
        gateway_enabled=True,
        database_url="sqlite+pysqlite:///" + (tmp_path / "gateway.db").as_posix(),
        data_encryption_key="data-encryption-key-for-tests-123456",
        mailbox_session_secret="mailbox-session-secret-for-tests-12345",
        admin_username="admin",
        admin_password="correct-password",
        admin_cookie_secure=False,
        admin_static_dir=str(tmp_path / "missing-admin-dist"),
    )


def test_gateway_enabled_app_boots_and_admin_can_manage_instances(tmp_path: Path) -> None:
    app = create_app(gateway_settings(tmp_path))

    with TestClient(app) as client:
        health = client.get("/healthz")
        login = client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        created = client.post(
            "/admin-api/instances",
            json={
                "name": "主实例",
                "base_url": "https://mail.example.com",
                "admin_email": "admin@example.com",
                "admin_password": "cloudmail-password",
            },
        )
        instance_id = created.json()["data"]["id"]
        domain = client.post(
            "/admin-api/domains",
            json={"instance_id": instance_id, "domain": "mail.example.com"},
        )
        overview = client.get("/admin-api/overview")

    assert health.status_code == 200
    assert health.json()["gatewayEnabled"] is True
    assert login.status_code == 200
    assert created.status_code == 201
    assert domain.status_code == 201
    assert overview.json()["data"]["instance_total"] == 1
    assert overview.json()["data"]["domain_total"] == 1


def test_admin_login_is_rate_limited_by_source(tmp_path: Path) -> None:
    settings = replace(
        gateway_settings(tmp_path),
        admin_login_rate_limit_per_minute=1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        first = client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        second = client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_legacy_token_broker_routes_are_not_exposed(tmp_path: Path) -> None:
    app = create_app(gateway_settings(tmp_path))

    with TestClient(app) as client:
        assert client.post("/v1/token").status_code == 404
        assert client.post("/v1/token/refresh", json={}).status_code == 404
        assert client.post("/api/public/genToken", json={}).status_code == 404
        assert client.get("/admin/status").status_code == 404
        assert client.post("/admin/token/refresh").status_code == 404


def test_schema_upgrade_adds_persisted_verification_code_column(tmp_path: Path) -> None:
    database = GatewayDatabase(tmp_path / "legacy-v2.db")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE gateway_schema(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO gateway_schema(version) VALUES (2)")
        connection.execute(
            """CREATE TABLE mailboxes (
                id TEXT PRIMARY KEY,
                address TEXT NOT NULL UNIQUE,
                domain_id BIGINT NOT NULL,
                instance_id BIGINT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                verification_status TEXT NOT NULL DEFAULT 'pending',
                provider_reference TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO mailboxes
            (id,address,domain_id,instance_id,created_at,updated_at)
            VALUES ('mbx-old','old@example.com',1,1,'2026-08-10T00:00:00+00:00','2026-08-10T00:00:00+00:00')"""
        )

    database.initialize()

    with database.read() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(mailboxes)").fetchall()}
        version = connection.execute("SELECT version FROM gateway_schema").fetchone()["version"]
        mailbox = connection.execute("SELECT verification_code FROM mailboxes WHERE id='mbx-old'").fetchone()

    assert "verification_code" in columns
    assert version == SCHEMA_VERSION == 3
    assert mailbox["verification_code"] == ""
