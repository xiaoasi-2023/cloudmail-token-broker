from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.admin_api import AdminApiContext, create_admin_router
from app.gateway.admin_auth import AdminSessionService, hash_admin_password
from app.gateway.database import GatewayDatabase
from app.gateway.repository import GatewayRepository


class TestCipher:
    def encrypt(self, plaintext: str) -> str:
        return "encrypted:" + plaintext[::-1]

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")[::-1]


def build_repository(tmp_path: Path) -> GatewayRepository:
    database = GatewayDatabase(tmp_path / "gateway.db")
    database.initialize()
    return GatewayRepository(database, TestCipher())


def build_client(tmp_path: Path, *, test_hook=None) -> tuple[TestClient, GatewayRepository]:
    repository = build_repository(tmp_path)
    sessions = AdminSessionService(
        repository.database,
        "admin",
        hash_admin_password("correct-password"),
        ttl_seconds=3600,
    )
    app = FastAPI()
    app.include_router(
        create_admin_router(
            AdminApiContext(
                repository=repository,
                sessions=sessions,
                instance_test_hook=test_hook,
                cookie_secure=False,
            )
        )
    )
    return TestClient(app), repository


def login(client: TestClient) -> None:
    response = client.post("/admin-api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert response.status_code == 200


def test_admin_requires_login_and_session_can_logout(tmp_path: Path) -> None:
    client, _repository = build_client(tmp_path)

    session_before = client.get("/admin-api/auth/session")
    unauthorized = client.get("/admin-api/overview")
    failed = client.post("/admin-api/auth/login", json={"username": "admin", "password": "wrong-password"})
    login(client)
    authorized = client.get("/admin-api/overview")
    logout = client.post("/admin-api/auth/logout")
    after_logout = client.get("/admin-api/overview")

    assert session_before.json()["authenticated"] is False
    assert unauthorized.status_code == 401
    assert failed.status_code == 401
    assert authorized.status_code == 200
    assert logout.status_code == 200
    assert after_logout.status_code == 401


def test_instance_and_domain_crud_never_returns_password(tmp_path: Path) -> None:
    client, repository = build_client(tmp_path)
    login(client)

    created = client.post(
        "/admin-api/instances",
        json={
            "name": "主实例",
            "base_url": "https://mail.example.com/",
            "admin_email": "admin@example.com",
            "admin_password": "cloudmail-secret",
        },
    )
    instance_id = created.json()["data"]["id"]
    listed = client.get("/admin-api/instances")
    updated = client.patch(f"/admin-api/instances/{instance_id}", json={"enabled": False})
    domain = client.post(
        "/admin-api/domains",
        json={"instance_id": instance_id, "domain": "Mail-A.Example.com.", "weight": 250},
    )
    domain_id = domain.json()["data"]["id"]
    domain_updated = client.patch(f"/admin-api/domains/{domain_id}", json={"weight": 300, "enabled": False})
    cleared = client.post(f"/admin-api/domains/{domain_id}/clear-cooldown")

    assert created.status_code == 201
    assert created.json()["data"]["base_url"] == "https://mail.example.com"
    assert "cloudmail-secret" not in created.text + listed.text + updated.text
    assert "admin_password" not in created.text + listed.text + updated.text
    assert repository.get_instance(instance_id, include_password=True)["admin_password"] == "cloudmail-secret"
    assert updated.json()["data"]["enabled"] is False
    assert domain.status_code == 201
    assert domain.json()["data"]["domain"] == "mail-a.example.com"
    assert domain_updated.json()["data"]["weight"] == 300
    assert cleared.json()["data"]["failure_count"] == 0


def test_domain_list_supports_empty_and_instance_filter(tmp_path: Path) -> None:
    client, repository = build_client(tmp_path)
    login(client)
    instance_a = repository.create_instance(
        {"name": "instance-a", "base_url": "https://a.example.com", "admin_email": "a@example.com", "admin_password": "secret"}
    )
    instance_b = repository.create_instance(
        {"name": "instance-b", "base_url": "https://b.example.com", "admin_email": "b@example.com", "admin_password": "secret"}
    )

    empty = client.get("/admin-api/domains")
    repository.create_domain({"instance_id": instance_a["id"], "domain": "a.example.com"})
    repository.create_domain({"instance_id": instance_b["id"], "domain": "b.example.com"})
    filtered = client.get(f"/admin-api/domains?instance_id={instance_a['id']}")

    assert empty.status_code == 200
    assert empty.json()["data"] == []
    assert filtered.status_code == 200
    assert [item["domain"] for item in filtered.json()["data"]] == ["a.example.com"]
    assert filtered.json()["data"][0]["instance_name"] == "instance-a"


def test_client_key_crud_and_authentication(tmp_path: Path) -> None:
    client, repository = build_client(tmp_path)
    login(client)

    created = client.post("/admin-api/client-keys", json={"name": "image2api"})
    item = created.json()["data"]
    assert created.status_code == 201
    assert item["api_key"].startswith("xmk_")
    assert repository.authenticate_client_key(item["api_key"])["name"] == "image2api"

    disabled = client.patch(f"/admin-api/client-keys/{item['id']}", json={"enabled": False})
    assert disabled.json()["data"]["enabled"] is False
    assert repository.authenticate_client_key(item["api_key"]) is None

    regenerated = client.post(f"/admin-api/client-keys/{item['id']}/regenerate").json()["data"]
    assert regenerated["api_key"] != item["api_key"]
    deleted = client.delete(f"/admin-api/client-keys/{item['id']}")
    assert deleted.status_code == 200


def test_parallel_admin_reads_do_not_trigger_sqlite_write_conflicts(tmp_path: Path) -> None:
    client, repository = build_client(tmp_path)
    login(client)
    instance = repository.create_instance(
        {"name": "instance-a", "base_url": "https://a.example.com", "admin_email": "a@example.com", "admin_password": "secret"}
    )
    repository.create_domain({"instance_id": instance["id"], "domain": "a.example.com"})

    def load_admin_data(index: int):
        path = "/admin-api/domains" if index % 2 == 0 else "/admin-api/instances"
        return client.get(path)

    with ThreadPoolExecutor(max_workers=16) as executor:
        responses = list(executor.map(load_admin_data, range(64)))

    assert {response.status_code for response in responses} == {200}


def test_duplicate_instance_and_domain_return_conflict(tmp_path: Path) -> None:
    client, _repository = build_client(tmp_path)
    login(client)
    payload = {
        "name": "instance-a",
        "base_url": "https://mail.example.com",
        "admin_email": "admin@example.com",
        "admin_password": "secret",
    }
    first = client.post("/admin-api/instances", json=payload)
    duplicate = client.post("/admin-api/instances", json=payload)
    instance_id = first.json()["data"]["id"]
    domain_payload = {"instance_id": instance_id, "domain": "mail.example.com"}
    client.post("/admin-api/domains", json=domain_payload)
    duplicate_domain = client.post("/admin-api/domains", json=domain_payload)

    assert duplicate.status_code == 409
    assert duplicate_domain.status_code == 409


def test_instance_test_hook_updates_health_without_exposing_credentials(tmp_path: Path) -> None:
    seen: dict = {}

    async def hook(instance: dict) -> dict:
        seen.update(instance)
        return {"ok": True, "latency_ms": 18}

    client, repository = build_client(tmp_path, test_hook=hook)
    login(client)
    created = client.post(
        "/admin-api/instances",
        json={
            "name": "instance-a",
            "base_url": "https://mail.example.com",
            "admin_email": "admin@example.com",
            "admin_password": "cloudmail-secret",
        },
    )
    instance_id = created.json()["data"]["id"]
    response = client.post(f"/admin-api/instances/{instance_id}/test")

    assert response.status_code == 200
    assert response.json()["data"]["latency_ms"] == 18
    assert "cloudmail-secret" not in response.text
    assert seen["admin_password"] == "cloudmail-secret"
    assert repository.get_instance(instance_id)["health_status"] == "healthy"


def test_overview_mailbox_and_log_lists_are_available(tmp_path: Path) -> None:
    client, repository = build_client(tmp_path)
    login(client)
    instance = repository.create_instance(
        {
            "name": "instance-a",
            "base_url": "https://mail.example.com",
            "admin_email": "admin@example.com",
            "admin_password": "secret",
        }
    )
    repository.create_domain({"instance_id": instance["id"], "domain": "mail.example.com"})

    overview = client.get("/admin-api/overview")
    mailboxes = client.get("/admin-api/mailboxes")
    logs = client.get("/admin-api/request-logs")

    assert overview.json()["data"]["instance_total"] == 1
    assert overview.json()["data"]["domain_total"] == 1
    assert mailboxes.json()["data"] == []
    assert logs.json()["data"] == []
