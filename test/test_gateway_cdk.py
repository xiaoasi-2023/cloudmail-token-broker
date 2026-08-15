from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.admin_api import AdminApiContext, create_admin_router
from app.gateway.admin_auth import AdminSessionService, hash_admin_password
from app.gateway.database import GatewayDatabase
from app.gateway.repository import GatewayRepository
from app.gateway.user_api import UserApiContext, create_user_router
from app.gateway.user_auth import UserSessionService
from app.gateway.user_repository import UserRepository


class TestCipher:
    def encrypt(self, plaintext: str) -> str:
        return "encrypted:" + plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")


def build_database(path: Path) -> tuple[GatewayDatabase, GatewayRepository, UserRepository]:
    database = GatewayDatabase(path)
    database.initialize()
    repository = GatewayRepository(database, TestCipher())
    users = UserRepository(database)
    users.ensure_admin("admin", hash_admin_password("correct-password"))
    return database, repository, users


def build_admin_client(
    repository: GatewayRepository,
    users: UserRepository,
) -> TestClient:
    sessions = AdminSessionService(
        repository.database,
        "admin",
        hash_admin_password("correct-password"),
        ttl_seconds=3600,
    )
    app = FastAPI()
    app.include_router(
        create_admin_router(
            AdminApiContext(repository=repository, sessions=sessions, users=users, cookie_secure=False)
        )
    )
    return TestClient(app)


def test_default_package_and_admin_cdk_management(tmp_path: Path) -> None:
    _database, repository, users = build_database(tmp_path / "cdk-admin.db")
    with build_admin_client(repository, users) as client:
        login = client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        packages = client.get("/admin-api/credit-packages")
        default_packages = packages.json()["data"]
        default_package = default_packages[0]
        created = client.post(
            "/admin-api/credit-packages",
            json={"name": "测试套餐", "points": 250, "price": 25, "purchaseUrl": "https://buy.test/cdk"},
        )
        package_id = created.json()["data"]["id"]
        generated = client.post(
            "/admin-api/cdks/generate",
            json={"packageId": package_id, "count": 3},
        )
        generated_items = generated.json()["data"]["items"]
        code = generated_items[0]["code"]
        listed = client.get(f"/admin-api/cdks?package_id={package_id}&status=unused")
        disabled = client.patch(f"/admin-api/cdks/{generated_items[0]['id']}/disable")
        disabled_list = client.get("/admin-api/cdks?status=disabled")
        package_disabled = client.post(f"/admin-api/credit-packages/{package_id}/disable")

    assert login.status_code == 200
    assert {item["points"] for item in default_packages} == {1000, 10000}
    assert {item["purchase_url"] for item in default_packages} == {
        "https://pay.ldxp.cn/item/vjxbeh",
        "https://pay.ldxp.cn/item/9z9op3",
    }
    assert default_package["points"] == 10000
    assert created.status_code == 201
    assert created.json()["data"]["purchase_url"] == "https://buy.test/cdk"
    assert generated.status_code == 201
    assert generated.json()["data"]["package_id"] == package_id
    assert generated.json()["data"]["quantity"] == 3
    assert len(generated.json()["data"]["items"]) == 3
    assert len({item["code"] for item in generated.json()["data"]["items"]}) == 3
    assert code.startswith("CDK-")
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 3
    assert disabled.status_code == 200
    assert disabled.json()["data"]["status"] == "disabled"
    assert len(disabled_list.json()["data"]) == 1
    assert package_disabled.json()["data"]["enabled"] is False


def test_user_redeem_is_transactional_and_idempotently_rejected(tmp_path: Path) -> None:
    _database, repository, users = build_database(tmp_path / "cdk-user.db")
    user = users.create_user(username="cdk-user", password="cdk-user-password")
    admin_sessions = AdminSessionService(
        repository.database,
        "admin",
        hash_admin_password("correct-password"),
        ttl_seconds=3600,
    )
    user_sessions = UserSessionService(repository.database, users, ttl_seconds=3600)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            AdminApiContext(repository=repository, sessions=admin_sessions, users=users, cookie_secure=False)
        )
    )
    app.include_router(create_user_router(UserApiContext(users=users, sessions=user_sessions, cookie_secure=False)))

    with TestClient(app) as client:
        assert client.post(
            "/admin-api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        ).status_code == 200
        package_id = repository.list_credit_packages()[0]["id"]
        generated = client.post("/admin-api/cdks/generate", json={"package_id": package_id, "count": 1})
        code = generated.json()["data"]["items"][0]["code"]
        assert client.post(
            "/user-api/auth/login",
            json={"username": "cdk-user", "password": "cdk-user-password"},
        ).status_code == 200
        packages = client.get("/user-api/credits/packages")
        redeemed = client.post("/user-api/credits/redeem-cdk", json={"cdkCode": code.lower()})
        duplicate = client.post("/user-api/credits/redeem", json={"code": code})
        credits = client.get("/user-api/credits")

    assert packages.status_code == 200
    assert packages.json()["data"][0]["points"] == 10000
    assert redeemed.status_code == 200
    assert redeemed.json()["data"]["points"] == 10000
    assert redeemed.json()["data"]["balance"] == 10000
    assert redeemed.json()["data"]["transaction_id"] > 0
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "CDK_ALREADY_REDEEMED"
    assert credits.json()["data"]["balance"] == 10000


def test_cdk_redemption_history_is_not_hidden_by_consumption_records(tmp_path: Path) -> None:
    database, repository, users = build_database(tmp_path / "cdk-history.db")
    user = users.create_user(username="cdk-history", password="cdk-history-password")
    package_id = repository.list_credit_packages()[0]["id"]
    code = repository.generate_cdks(package_id, 1)[0]["code"]
    sessions = UserSessionService(database, users, ttl_seconds=3600)
    app = FastAPI()
    app.include_router(create_user_router(UserApiContext(users=users, sessions=sessions, cookie_secure=False)))

    with TestClient(app) as client:
        assert client.post(
            "/user-api/auth/login",
            json={"username": "cdk-history", "password": "cdk-history-password"},
        ).status_code == 200
        assert client.post("/user-api/credits/redeem-cdk", json={"code": code}).status_code == 200

        with database.transaction() as connection:
            for index in range(30):
                connection.execute(
                    """INSERT INTO credit_transactions
                    (user_id, type, status, amount, balance_after, reference_type,
                    reference_id, remark, created_at)
                    VALUES (?, 'consume', 'completed', -1, ?, 'mailbox', ?, '创建邮箱扣除积分', ?)""",
                    (
                        user["id"],
                        9999 - index,
                        f"mailbox-{index}",
                        "2026-08-15T00:00:00+00:00",
                    ),
                )
            connection.execute(
                "UPDATE users SET credit_balance=? WHERE id=?",
                (9970, user["id"]),
            )

        recent = client.get("/user-api/credits?limit=20")
        redemptions = client.get("/user-api/credits/cdk-redemptions?limit=20")

    assert recent.status_code == 200
    assert all(item["reference_type"] != "cdk" for item in recent.json()["data"]["transactions"])
    assert redemptions.status_code == 200
    assert len(redemptions.json()["data"]) == 1
    assert redemptions.json()["data"][0]["reference_id"] == code
    assert redemptions.json()["data"][0]["amount"] == 10000


def test_concurrent_redeem_has_exactly_one_success(tmp_path: Path) -> None:
    database, repository, users = build_database(tmp_path / "cdk-concurrency.db")
    user_a = users.create_user(username="cdk-a", password="cdk-a-password")
    user_b = users.create_user(username="cdk-b", password="cdk-b-password")
    package_id = repository.list_credit_packages()[0]["id"]
    code = repository.generate_cdks(package_id, 1)[0]["code"]

    def redeem(user_id: int) -> str:
        try:
            users.redeem_cdk(user_id, code)
            return "success"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(redeem, [user_a["id"], user_b["id"]]))

    assert results.count("success") == 1
    assert sum(result == "CDK_ALREADY_REDEEMED" for result in results) == 1
    assert users.get_credits(user_a["id"])["balance"] + users.get_credits(user_b["id"])["balance"] == 10000
    with database.read() as connection:
        cdk = connection.execute("SELECT status, redeemed_by FROM credit_cdks WHERE code=?", (code,)).fetchone()
        transactions = connection.execute(
            "SELECT COUNT(*) AS total, MIN(type) AS type FROM credit_transactions WHERE reference_type='cdk' AND reference_id=?",
            (code,),
        ).fetchone()
    assert cdk["status"] == "redeemed"
    assert cdk["redeemed_by"] in {user_a["id"], user_b["id"]}
    assert transactions["total"] == 1
    assert transactions["type"] == "admin_adjust"
