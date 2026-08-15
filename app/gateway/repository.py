from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from app.gateway.crypto import SecretCipher
from app.gateway.database import GatewayDatabase


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _public_instance(row: Any) -> dict[str, Any]:
    result = dict(row)
    result.pop("admin_password_encrypted", None)
    result["verify_tls"] = bool(result["verify_tls"])
    result["enabled"] = bool(result["enabled"])
    return result


def _public_domain(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    return result


def _public_credit_package(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    return result


def _public_cdk(row: Any) -> dict[str, Any]:
    result = dict(row)
    if "status" in result:
        result["enabled"] = result["status"] == "unused"
    return result


class GatewayRepository:
    def __init__(self, database: GatewayDatabase, cipher: SecretCipher) -> None:
        self.database = database
        self.cipher = cipher

    def create_instance(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        password = data.get("admin_password", "")
        if not password:
            raise ValueError("管理员密码不能为空")
        with self.database.transaction() as connection:
            inserted = connection.execute(
                """INSERT INTO cloudmail_instances
                (name, base_url, admin_email, admin_password_encrypted, proxy_url, verify_tls, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id""",
                (
                    data["name"].strip(), data["base_url"].rstrip("/"), data["admin_email"].strip(),
                    self.cipher.encrypt(password), data.get("proxy_url", "").strip(),
                    int(data.get("verify_tls", True)), int(data.get("enabled", True)), now, now,
                ),
            )
            instance_id = int(inserted.fetchone()["id"])
            row = connection.execute("SELECT * FROM cloudmail_instances WHERE id = ?", (instance_id,)).fetchone()
        return _public_instance(row)

    def list_instances(self) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT i.*, COUNT(d.id) AS domain_count
                FROM cloudmail_instances i LEFT JOIN mail_domains d ON d.instance_id = i.id
                GROUP BY i.id ORDER BY i.id"""
            ).fetchall()
        return [_public_instance(row) for row in rows]

    def get_instance(self, instance_id: int, *, include_password: bool = False) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM cloudmail_instances WHERE id = ?", (instance_id,)).fetchone()
        if row is None:
            return None
        result = _public_instance(row)
        if include_password:
            result["admin_password"] = self.cipher.decrypt(row["admin_password_encrypted"])
        return result

    def update_instance(self, instance_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_instance(instance_id, include_password=True)
        if current is None:
            return None
        password = data.get("admin_password") or current["admin_password"]
        values = {
            "name": data.get("name", current["name"]).strip(),
            "base_url": data.get("base_url", current["base_url"]).rstrip("/"),
            "admin_email": data.get("admin_email", current["admin_email"]).strip(),
            "admin_password_encrypted": self.cipher.encrypt(password),
            "proxy_url": data.get("proxy_url", current["proxy_url"]).strip(),
            "verify_tls": int(data.get("verify_tls", current["verify_tls"])),
            "enabled": int(data.get("enabled", current["enabled"])),
            "updated_at": utc_now(),
        }
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE cloudmail_instances SET name=:name, base_url=:base_url, admin_email=:admin_email,
                admin_password_encrypted=:admin_password_encrypted, proxy_url=:proxy_url, verify_tls=:verify_tls,
                enabled=:enabled, updated_at=:updated_at WHERE id=:id""",
                {**values, "id": instance_id},
            )
        return self.get_instance(instance_id)

    def delete_instance(self, instance_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM cloudmail_instances WHERE id = ?", (instance_id,))
        return cursor.rowcount > 0

    def set_instance_health(self, instance_id: int, status: str, error: str = "") -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE cloudmail_instances SET health_status=?, last_error=?, last_checked_at=?, updated_at=? WHERE id=?",
                (status, error[:1000], utc_now(), utc_now(), instance_id),
            )

    def create_domain(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        domain = data["domain"].strip().lower().rstrip(".")
        with self.database.transaction() as connection:
            inserted = connection.execute(
                """INSERT INTO mail_domains(instance_id, domain, enabled, weight, remark, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id""",
                (data["instance_id"], domain, int(data.get("enabled", True)), data.get("weight", 100), data.get("remark", ""), now, now),
            )
            domain_id = int(inserted.fetchone()["id"])
            row = connection.execute("SELECT * FROM mail_domains WHERE id = ?", (domain_id,)).fetchone()
        return _public_domain(row)

    def list_domains(self, instance_id: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT d.*, COALESCE(i.name, '未关联实例') AS instance_name FROM mail_domains d
                 LEFT JOIN cloudmail_instances i ON i.id=d.instance_id"""
        params: tuple[Any, ...] = ()
        if instance_id is not None:
            sql += " WHERE d.instance_id = ?"
            params = (instance_id,)
        sql += " ORDER BY d.id"
        with self.database.read() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_public_domain(row) for row in rows]

    def get_domain(self, domain_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM mail_domains WHERE id = ?", (domain_id,)).fetchone()
        return _public_domain(row) if row else None

    def update_domain(self, domain_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_domain(domain_id)
        if current is None:
            return None
        values = {
            "instance_id": data.get("instance_id", current["instance_id"]),
            "domain": data.get("domain", current["domain"]).strip().lower().rstrip("."),
            "enabled": int(data.get("enabled", current["enabled"])),
            "weight": data.get("weight", current["weight"]),
            "remark": data.get("remark", current["remark"]),
            "updated_at": utc_now(),
            "id": domain_id,
        }
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE mail_domains SET instance_id=:instance_id, domain=:domain, enabled=:enabled,
                weight=:weight, remark=:remark, updated_at=:updated_at WHERE id=:id""", values,
            )
        return self.get_domain(domain_id)

    def delete_domain(self, domain_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM mail_domains WHERE id = ?", (domain_id,))
        return cursor.rowcount > 0

    def clear_domain_cooldown(self, domain_id: int) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE mail_domains SET status='unknown', failure_count=0, cooldown_until=NULL, updated_at=? WHERE id=?""",
                (utc_now(), domain_id),
            )
        return self.get_domain(domain_id)

    def overview(self) -> dict[str, int]:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT
                (SELECT COUNT(*) FROM cloudmail_instances) AS instance_total,
                (SELECT COUNT(*) FROM cloudmail_instances WHERE enabled=1) AS instance_enabled,
                (SELECT COUNT(*) FROM cloudmail_instances WHERE health_status='healthy') AS instance_healthy,
                (SELECT COUNT(*) FROM mail_domains) AS domain_total,
                (SELECT COUNT(*) FROM mail_domains WHERE enabled=1) AS domain_enabled,
                (SELECT COUNT(*) FROM mailboxes) AS mailbox_total,
                (SELECT COUNT(*) FROM gateway_request_logs WHERE status_code >= 400) AS error_total"""
            ).fetchone()
        return dict(row)

    def create_credit_package(self, data: dict[str, Any]) -> dict[str, Any]:
        points = int(data["points"])
        price = int(data.get("price", 0))
        if points <= 0:
            raise ValueError("积分数量必须大于 0")
        if price < 0:
            raise ValueError("套餐价格不能为负数")
        name = str(data.get("name") or f"{points}积分/{price}元").strip()
        slug = str(data.get("slug") or f"package-{uuid.uuid4().hex}").strip().lower()
        purchase_url = str(data.get("purchase_url") or "").strip()
        now = utc_now()
        with self.database.transaction() as connection:
            inserted = connection.execute(
                """INSERT INTO credit_packages
                (slug, name, points, price, purchase_url, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (slug, name, points, price, purchase_url, int(data.get("enabled", True)), now, now),
            )
            package_id = int(inserted.fetchone()["id"])
            row = connection.execute("SELECT * FROM credit_packages WHERE id=?", (package_id,)).fetchone()
        return _public_credit_package(row)

    def list_credit_packages(
        self,
        *,
        enabled: bool | None = None,
        keyword: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        normalized_keyword = keyword.strip().lower()
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            conditions.append(
                "(LOWER(p.slug) LIKE ? OR LOWER(p.name) LIKE ? OR LOWER(p.purchase_url) LIKE ?)"
            )
            params.extend([like_keyword, like_keyword, like_keyword])
        if enabled is not None:
            conditions.append("p.enabled=?")
            params.append(int(enabled))
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with self.database.read() as connection:
            rows = connection.execute(
                f"""SELECT p.*, COUNT(c.id) AS cdk_total,
                SUM(CASE WHEN c.status='unused' THEN 1 ELSE 0 END) AS cdk_unused_total,
                SUM(CASE WHEN c.status='redeemed' THEN 1 ELSE 0 END) AS cdk_redeemed_total
                FROM credit_packages p LEFT JOIN credit_cdks c ON c.package_id=p.id
                {where_clause}
                GROUP BY p.id ORDER BY p.id DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [_public_credit_package(row) for row in rows]

    def get_credit_package(self, package_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM credit_packages WHERE id=?", (package_id,)).fetchone()
        return _public_credit_package(row) if row else None

    def update_credit_package(self, package_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_credit_package(package_id)
        if current is None:
            return None
        points = int(data.get("points", current["points"]))
        price = int(data.get("price", current["price"]))
        if points <= 0:
            raise ValueError("积分数量必须大于 0")
        if price < 0:
            raise ValueError("套餐价格不能为负数")
        values = {
            "slug": str(data.get("slug", current["slug"])).strip().lower(),
            "name": str(data.get("name", current["name"])).strip(),
            "points": points,
            "price": price,
            "purchase_url": str(data.get("purchase_url", current["purchase_url"]) or "").strip(),
            "enabled": int(data.get("enabled", current["enabled"])),
            "updated_at": utc_now(),
            "id": package_id,
        }
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE credit_packages SET slug=:slug, name=:name, points=:points, price=:price,
                purchase_url=:purchase_url, enabled=:enabled, updated_at=:updated_at WHERE id=:id""",
                values,
            )
        return self.get_credit_package(package_id)

    def delete_credit_package(self, package_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM credit_packages WHERE id=?", (package_id,))
        return cursor.rowcount > 0

    def disable_credit_package(self, package_id: int) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE credit_packages SET enabled=0, updated_at=? WHERE id=?",
                (utc_now(), package_id),
            )
        return self.get_credit_package(package_id)

    def generate_cdks(self, package_id: int, count: int, admin_user_id: int | None = None) -> list[dict[str, Any]]:
        if count < 1:
            raise ValueError("CDK 数量必须大于 0")
        if count > 10000:
            raise ValueError("单次最多生成 10000 个 CDK")
        batch_id = uuid.uuid4().hex
        now = utc_now()
        generated: list[dict[str, Any]] = []
        with self.database.transaction() as connection:
            package = connection.execute(
                "SELECT id, slug, name, points, enabled FROM credit_packages WHERE id=?",
                (package_id,),
            ).fetchone()
            if package is None:
                raise ValueError("PACKAGE_NOT_FOUND")
            if not package["enabled"]:
                raise ValueError("PACKAGE_DISABLED")
            for _ in range(count):
                while True:
                    code = f"CDK-{secrets.token_hex(12).upper()}"
                    inserted = connection.execute(
                        """INSERT INTO credit_cdks
                        (package_id, code, points, status, generated_by, batch_id, created_at)
                        VALUES (?, ?, ?, 'unused', ?, ?, ?)
                        ON CONFLICT(code) DO NOTHING RETURNING id""",
                        (package_id, code, package["points"], admin_user_id, batch_id, now),
                    )
                    inserted_row = inserted.fetchone()
                    if inserted_row is not None:
                        cdk_id = int(inserted_row["id"])
                        generated.append(
                            {
                                "id": cdk_id,
                                "package_id": package_id,
                                "package_slug": package["slug"],
                                "package_name": package["name"],
                                "code": code,
                                "points": int(package["points"]),
                                "status": "unused",
                                "enabled": True,
                                "generated_by": admin_user_id,
                                "batch_id": batch_id,
                                "created_at": now,
                            }
                        )
                        break
        return generated

    def list_cdks(
        self,
        *,
        status: str = "",
        package_id: int | None = None,
        keyword: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        normalized_status = status.strip().lower()
        if normalized_status:
            conditions.append("c.status=?")
            params.append(normalized_status)
        if package_id is not None:
            conditions.append("c.package_id=?")
            params.append(package_id)
        normalized_keyword = keyword.strip().lower()
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            conditions.append(
                "(LOWER(c.code) LIKE ? OR LOWER(p.name) LIKE ? OR LOWER(p.slug) LIKE ? OR LOWER(u.username) LIKE ?)"
            )
            params.extend([like_keyword, like_keyword, like_keyword, like_keyword])
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with self.database.read() as connection:
            rows = connection.execute(
                f"""SELECT c.*, p.slug AS package_slug, p.name AS package_name,
                u.username AS redeemed_username
                FROM credit_cdks c JOIN credit_packages p ON p.id=c.package_id
                LEFT JOIN users u ON u.id=c.redeemed_by
                {where_clause}
                ORDER BY c.id DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [_public_cdk(row) for row in rows]

    def get_cdk(self, cdk_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT c.*, p.slug AS package_slug, p.name AS package_name,
                u.username AS redeemed_username
                FROM credit_cdks c JOIN credit_packages p ON p.id=c.package_id
                LEFT JOIN users u ON u.id=c.redeemed_by WHERE c.id=?""",
                (cdk_id,),
            ).fetchone()
        return _public_cdk(row) if row else None

    def disable_cdk(self, cdk_id: int, admin_user_id: int | None = None) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE credit_cdks SET status='disabled', disabled_at=?, disabled_by=?
                WHERE id=? AND status='unused'""",
                (utc_now(), admin_user_id, cdk_id),
            )
        return self.get_cdk(cdk_id)

    def list_mailboxes(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        keyword: str = "",
        purpose: str = "",
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        normalized_keyword = keyword.strip().lower()
        normalized_purpose = purpose.strip().lower()
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            conditions.append(
                "(LOWER(m.address) LIKE ? OR LOWER(d.domain) LIKE ? OR LOWER(m.source) LIKE ?)"
            )
            params.extend([like_keyword, like_keyword, like_keyword])
        if normalized_purpose:
            conditions.append("LOWER(m.purpose) = ?")
            params.append(normalized_purpose)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with self.database.read() as connection:
            rows = connection.execute(
                f"""SELECT m.*, d.domain, i.name AS instance_name FROM mailboxes m
                JOIN mail_domains d ON d.id=m.domain_id JOIN cloudmail_instances i ON i.id=m.instance_id
                {where_clause}
                ORDER BY m.created_at DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_request_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        keyword: str = "",
        status_group: str = "",
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        normalized_keyword = keyword.strip().lower()
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            conditions.append(
                "(LOWER(l.endpoint) LIKE ? OR LOWER(l.source) LIKE ? OR "
                "LOWER(l.error_code) LIKE ? OR LOWER(l.error_message) LIKE ? OR "
                "LOWER(u.username) LIKE ? OR LOWER(u.email) LIKE ?)"
            )
            params.extend([like_keyword, like_keyword, like_keyword, like_keyword, like_keyword, like_keyword])
        normalized_status = status_group.strip().lower()
        if normalized_status == "success":
            conditions.append("l.status_code BETWEEN 200 AND 399")
        elif normalized_status == "client_error":
            conditions.append("l.status_code BETWEEN 400 AND 499")
        elif normalized_status == "server_error":
            conditions.append("l.status_code >= 500")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with self.database.read() as connection:
            rows = connection.execute(
                f"""SELECT l.*, l.endpoint AS path, u.username AS user_username,
                u.email AS user_email
                FROM gateway_request_logs l LEFT JOIN users u ON u.id=l.user_id
                {where_clause}
                ORDER BY l.created_at DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def log_request(
        self,
        *,
        request_id: str,
        endpoint: str,
        method: str,
        source: str,
        status_code: int,
        duration_ms: int,
        user_id: int | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO gateway_request_logs
                (request_id, endpoint, method, source, user_id, status_code, duration_ms,
                 error_code, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id[:100], endpoint[:500], method[:20], source[:100],
                    user_id, int(status_code), max(0, int(duration_ms)),
                    error_code[:100], error_message[:1000], utc_now(),
                ),
            )

    def audit(self, username: str, action: str, target_type: str = "", target_id: str = "", detail: str = "") -> None:
        safe_detail = detail[:1000]
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO admin_audit_logs(username, action, target_type, target_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, action, target_type, target_id, safe_detail, utc_now()),
            )

    def audit_json(self, username: str, action: str, target_type: str, target_id: str, detail: dict[str, Any]) -> None:
        self.audit(username, action, target_type, target_id, json.dumps(detail, ensure_ascii=False))
