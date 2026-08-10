from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def gateway_settings(tmp_path: Path) -> Settings:
    return Settings(
        broker_public_access=True,
        gateway_enabled=True,
        gateway_database_path=str(tmp_path / "gateway.db"),
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
