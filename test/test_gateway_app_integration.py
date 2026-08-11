from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.database import GatewayDatabase, SCHEMA_VERSION
from app.gateway.registration import RegistrationEmailSender
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


def test_root_redirects_to_user_center(tmp_path: Path) -> None:
    app = create_app(gateway_settings(tmp_path))

    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/user/"


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
    assert health.json()["pop3Enabled"] is True
    assert health.json()["pop3Listening"] is True
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
    assert version == SCHEMA_VERSION == 7
    assert mailbox["verification_code"] == ""


def test_admin_pop_auth_code_is_stored_and_returned_as_plaintext(tmp_path: Path) -> None:
    app = create_app(gateway_settings(tmp_path))

    with TestClient(app) as client:
        login = client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        saved = client.put(
            "/admin-api/pop-auth-code",
            json={"auth_code": "plain-admin-pop-code"},
        )
        loaded = client.get("/admin-api/pop-auth-code")
        users = client.get("/admin-api/users")

    assert login.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["data"]["admin_pop_auth_code"] == "plain-admin-pop-code"
    assert loaded.status_code == 200
    assert loaded.json()["data"] == {
        "configured": True,
        "admin_pop_auth_code": "plain-admin-pop-code",
        "legacy_hash_only": False,
        "updated_at": loaded.json()["data"]["updated_at"],
    }
    assert "plain-admin-pop-code" not in users.text

    repository = app.state.user_repository
    assert repository.verify_admin_pop_auth_code("plain-admin-pop-code") is True
    assert repository.verify_admin_pop_auth_code("wrong-admin-pop-code") is False
    with repository.database.read() as connection:
        stored = connection.execute(
            """SELECT admin_pop_auth_code, admin_pop_auth_code_hash
            FROM users WHERE role='admin'"""
        ).fetchone()
    assert stored["admin_pop_auth_code"] == "plain-admin-pop-code"
    assert stored["admin_pop_auth_code_hash"] is None


def test_user_pop_auth_code_is_stored_and_returned_as_plaintext(tmp_path: Path) -> None:
    settings = replace(
        gateway_settings(tmp_path),
        pop3_public_host="pop.example.com",
        pop3_public_port=18110,
    )
    app = create_app(settings)
    user = app.state.user_repository.create_user(
        username="pop-user",
        password="user-password",
        email="pop-user@example.com",
    )

    with TestClient(app) as client:
        login = client.post(
            "/user-api/auth/login",
            json={"username": "pop-user", "password": "user-password"},
        )
        saved = client.put(
            "/user-api/auth-code",
            json={"userAuthCode": "plain-user-pop-code"},
        )
        loaded = client.get("/user-api/auth-code")

    assert login.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["data"]["user_auth_code"] == "plain-user-pop-code"
    assert loaded.status_code == 200
    assert loaded.json()["data"] == {
        "configured": True,
        "user_auth_code": "plain-user-pop-code",
        "legacy_hash_only": False,
        "updated_at": loaded.json()["data"]["updated_at"],
        "pop_host": "pop.example.com",
        "pop_port": 18110,
        "mailboxes": [],
    }
    assert app.state.user_repository.verify_user_pop_auth_code(
        int(user["id"]),
        "plain-user-pop-code",
    ) is True
    with app.state.user_repository.database.read() as connection:
        stored = connection.execute(
            "SELECT user_auth_code, user_auth_code_hash FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
    assert stored["user_auth_code"] == "plain-user-pop-code"
    assert stored["user_auth_code_hash"] is None


def test_user_api_key_is_stored_listed_and_regenerated_as_plaintext(tmp_path: Path) -> None:
    app = create_app(gateway_settings(tmp_path))
    user = app.state.user_repository.create_user(
        username="api-key-user",
        password="user-password",
        email="api-key-user@example.com",
    )

    with TestClient(app) as client:
        login = client.post(
            "/user-api/auth/login",
            json={"username": "api-key-user", "password": "user-password"},
        )
        created = client.post(
            "/user-api/api-keys",
            json={"name": "image2api"},
        )
        first_key = created.json()["data"]["api_key"]
        listed = client.get("/user-api/api-keys")
        regenerated = client.post(
            f"/user-api/api-keys/{created.json()['data']['id']}/regenerate"
        )
        second_key = regenerated.json()["data"]["api_key"]
        listed_after = client.get("/user-api/api-keys")

    assert login.status_code == 200
    assert created.status_code == 201
    assert first_key.startswith("xmk_")
    assert listed.json()["data"][0]["api_key"] == first_key
    assert listed.json()["data"][0]["legacy_hash_only"] is False
    assert regenerated.status_code == 200
    assert second_key.startswith("xmk_")
    assert second_key != first_key
    assert listed_after.json()["data"][0]["api_key"] == second_key
    assert app.state.user_repository.authenticate_api_key(first_key) is None
    authenticated = app.state.user_repository.authenticate_api_key(second_key)
    assert authenticated is not None
    assert int(authenticated["user_id"]) == int(user["id"])
    with app.state.user_repository.database.read() as connection:
        stored = connection.execute(
            "SELECT api_key, key_hash FROM user_api_keys WHERE id=?",
            (created.json()["data"]["id"],),
        ).fetchone()
    assert stored["api_key"] == second_key
    assert stored["key_hash"] != second_key


def test_user_can_register_with_email_code_and_login_by_email(tmp_path: Path, monkeypatch) -> None:
    sent: dict[str, object] = {}

    def fake_send_code(_sender, email: str, code: str, ttl_seconds: int) -> None:
        sent.update(email=email, code=code, ttl_seconds=ttl_seconds)

    monkeypatch.setattr(RegistrationEmailSender, "send_code", fake_send_code)
    settings = replace(
        gateway_settings(tmp_path),
        user_registration_enabled=True,
        smtp_host="smtp.example.com",
        smtp_username="notice@example.com",
        smtp_password="smtp-authorization-code",
        smtp_from="notice@example.com",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        config = client.get("/user-api/auth/registration-config")
        sent_response = client.post(
            "/user-api/auth/register-code",
            json={"email": "new-user@example.com"},
        )
        invalid = client.post(
            "/user-api/auth/register",
            json={
                "username": "new-user",
                "email": "new-user@example.com",
                "password": "register-password",
                "code": "000000",
            },
        )
        registered = client.post(
            "/user-api/auth/register",
            json={
                "username": "new-user",
                "email": "new-user@example.com",
                "password": "register-password",
                "code": sent["code"],
            },
        )
        login = client.post(
            "/user-api/auth/login",
            json={"username": "new-user@example.com", "password": "register-password"},
        )
        profile = client.get("/user-api/me")

    assert config.json()["data"]["enabled"] is True
    assert sent_response.status_code == 200
    assert sent["email"] == "new-user@example.com"
    assert len(str(sent["code"])) == 6
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "REGISTER_CODE_INVALID"
    assert registered.status_code == 201
    assert registered.json()["data"]["email"] == "new-user@example.com"
    assert login.status_code == 200
    assert profile.status_code == 200
    assert profile.json()["data"]["username"] == "new-user"

    database = GatewayDatabase(settings.database_url)
    with database.read() as connection:
        stored = connection.execute(
            "SELECT code_hash, consumed FROM user_registration_codes WHERE email=?",
            ("new-user@example.com",),
        ).fetchone()
    database.dispose()
    assert stored["consumed"] == 1
    assert str(sent["code"]) not in stored["code_hash"]
