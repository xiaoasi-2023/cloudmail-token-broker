from __future__ import annotations

import hashlib
import hmac
import secrets
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from app.gateway.admin_auth import hash_admin_password, verify_admin_password
from app.gateway.database import GatewayDatabase


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_authenticated_user_id: ContextVar[int | None] = ContextVar(
    "gateway_authenticated_user_id",
    default=None,
)


def get_authenticated_user_id() -> int | None:
    return _authenticated_user_id.get()


def _public_user(row: Any) -> dict[str, Any]:
    item = dict(row)
    item.pop("password_hash", None)
    item.pop("user_auth_code_hash", None)
    item.pop("admin_pop_auth_code_hash", None)
    item.pop("admin_pop_auth_code", None)
    item["pop_enabled"] = bool(item["pop_enabled"])
    item["has_user_auth_code"] = bool(row["user_auth_code_hash"])
    item["has_admin_pop_auth_code"] = bool(
        row["admin_pop_auth_code"] or row["admin_pop_auth_code_hash"]
    )
    return item


def _public_api_key(row: Any, *, plaintext: str = "") -> dict[str, Any]:
    item = {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "enabled": bool(row["enabled"]),
        "last_used_at": row["last_used_at"],
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
    }
    if plaintext:
        item["api_key"] = plaintext
    else:
        item["masked_key"] = f"{row['key_prefix']}..."
    return item


class UserRepository:
    def __init__(self, database: GatewayDatabase) -> None:
        self.database = database

    def ensure_admin(self, username: str, password_hash: str) -> dict[str, Any]:
        normalized_username = username.strip().lower()
        with self.database.transaction() as connection:
            admin = connection.execute(
                "SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1"
            ).fetchone()
            if admin is not None:
                if admin["username"] != normalized_username:
                    raise RuntimeError("数据库中已存在其他管理员账号")
                return _public_user(admin)

            current = utc_now()
            inserted = connection.execute(
                """INSERT INTO users
                (username, password_hash, role, status, pop_enabled, credit_balance, created_at, updated_at)
                VALUES (?, ?, 'admin', 'active', 1, 0, ?, ?) RETURNING id""",
                (normalized_username, password_hash, current, current),
            )
            user_id = int(inserted.fetchone()["id"])
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _public_user(row)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _public_user(row) if row else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? OR email=?",
                (username.strip().lower(), username.strip().lower()),
            ).fetchone()
        return _public_user(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
            ).fetchone()
        return _public_user(row) if row else None

    def _get_user_with_secret(self, user_id: int) -> Any | None:
        with self.database.read() as connection:
            return connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def _get_user_with_secret_by_username(self, username: str) -> Any | None:
        with self.database.read() as connection:
            return connection.execute(
                "SELECT * FROM users WHERE username=? OR email=?",
                (username.strip().lower(), username.strip().lower()),
            ).fetchone()

    @staticmethod
    def _insert_user(
        connection: Any,
        *,
        username: str,
        email: str | None,
        password_hash: str,
        initial_points: int | None,
        current: str,
    ) -> Any:
        rule = connection.execute(
            "SELECT initial_user_points FROM credit_rules WHERE operation='create_mailbox'"
        ).fetchone()
        points = int(initial_points if initial_points is not None else rule["initial_user_points"])
        inserted = connection.execute(
            """INSERT INTO users
            (username, email, password_hash, role, status, pop_enabled, credit_balance, created_at, updated_at)
            VALUES (?, ?, ?, 'user', 'active', 1, ?, ?, ?) RETURNING id""",
            (username, email, password_hash, points, current, current),
        )
        user_id = int(inserted.fetchone()["id"])
        if points:
            connection.execute(
                """INSERT INTO credit_transactions
                (user_id, type, status, amount, balance_after, reference_type, reference_id, remark, created_at)
                VALUES (?, 'admin_adjust', 'completed', ?, ?, 'admin', ?, '新用户初始积分', ?)""",
                (user_id, points, points, str(user_id), current),
            )
        return connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def create_user(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        initial_points: int | None = None,
    ) -> dict[str, Any]:
        normalized_username = username.strip().lower()
        normalized_email = email.strip().lower() if email else None
        password_hash = hash_admin_password(password)
        current = utc_now()

        with self.database.transaction() as connection:
            row = self._insert_user(
                connection,
                username=normalized_username,
                email=normalized_email,
                password_hash=password_hash,
                initial_points=initial_points,
                current=current,
            )
        return _public_user(row)

    def create_user_from_registration(
        self,
        *,
        username: str,
        email: str,
        password: str,
        code_hash: str,
        max_attempts: int = 5,
    ) -> dict[str, Any] | None:
        normalized_username = username.strip().lower()
        normalized_email = email.strip().lower()
        password_hash = hash_admin_password(password)
        current = utc_now()
        now = datetime.now(UTC)

        with self.database.transaction() as connection:
            code_row = connection.execute(
                """SELECT * FROM user_registration_codes
                WHERE email=? AND consumed=0 ORDER BY created_at DESC LIMIT 1""",
                (normalized_email,),
            ).fetchone()
            if code_row is None:
                self.error_code = "REGISTER_CODE_INVALID"
                self.error = "验证码错误或已过期"
                return None

            expires_at = datetime.fromisoformat(str(code_row["expires_at"]))
            attempts = int(code_row["attempts"] or 0)
            if expires_at <= now or attempts >= max_attempts:
                connection.execute(
                    "UPDATE user_registration_codes SET consumed=1 WHERE id=?",
                    (code_row["id"],),
                )
                self.error_code = "REGISTER_CODE_INVALID"
                self.error = "验证码错误或已过期"
                return None

            if not hmac.compare_digest(str(code_row["code_hash"]), code_hash):
                next_attempts = attempts + 1
                connection.execute(
                    """UPDATE user_registration_codes SET attempts=?, consumed=? WHERE id=?""",
                    (next_attempts, 1 if next_attempts >= max_attempts else 0, code_row["id"]),
                )
                self.error_code = "REGISTER_CODE_INVALID"
                self.error = "验证码错误或已过期"
                return None

            row = self._insert_user(
                connection,
                username=normalized_username,
                email=normalized_email,
                password_hash=password_hash,
                initial_points=None,
                current=current,
            )
            connection.execute(
                "UPDATE user_registration_codes SET consumed=1 WHERE id=?",
                (code_row["id"],),
            )
        return _public_user(row)

    def verify_login(self, username: str, password: str) -> dict[str, Any] | None:
        row = self._get_user_with_secret_by_username(username)
        if row is None or row["status"] != "active":
            return None
        if not verify_admin_password(password, row["password_hash"]):
            return None
        return _public_user(row)

    def change_password(self, user_id: int, current_password: str, new_password: str) -> bool:
        row = self._get_user_with_secret(user_id)
        if row is None or not verify_admin_password(current_password, row["password_hash"]):
            self.error = "当前密码错误"
            return False
        try:
            password_hash = hash_admin_password(new_password)
        except ValueError as exc:
            self.error = str(exc)
            return False
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (password_hash, utc_now(), user_id),
            )
            connection.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        return True

    def list_users(self) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT u.*, COUNT(k.id) AS api_key_count
                FROM users u LEFT JOIN user_api_keys k
                ON k.user_id=u.id AND k.enabled=1 AND k.revoked_at IS NULL
                GROUP BY u.id ORDER BY u.id"""
            ).fetchall()
        return [_public_user(row) for row in rows]

    def set_user_enabled(self, user_id: int, enabled: bool) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None or row["role"] != "user":
                return None
            status = "active" if enabled else "disabled"
            connection.execute(
                "UPDATE users SET status=?, updated_at=? WHERE id=?",
                (status, utc_now(), user_id),
            )
            if not enabled:
                connection.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _public_user(row)

    def set_user_auth_code(self, user_id: int, auth_code: str) -> dict[str, Any] | None:
        try:
            auth_code_hash = hash_admin_password(auth_code)
        except ValueError as exc:
            self.error = str(exc)
            return None
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None or row["role"] != "user":
                self.error = "用户不存在"
                return None
            connection.execute(
                """UPDATE users SET user_auth_code_hash=?, user_auth_code_updated_at=?,
                pop_failed_attempts=0, pop_locked_until=NULL, updated_at=? WHERE id=?""",
                (auth_code_hash, utc_now(), utc_now(), user_id),
            )
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _public_user(row)

    def clear_user_auth_code(self, user_id: int) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None or row["role"] != "user":
                return None
            connection.execute(
                """UPDATE users SET user_auth_code_hash=NULL, user_auth_code_updated_at=NULL,
                pop_failed_attempts=0, pop_locked_until=NULL, updated_at=? WHERE id=?""",
                (utc_now(), user_id),
            )
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _public_user(row)

    def set_admin_pop_auth_code(self, auth_code: str) -> dict[str, Any] | None:
        normalized_auth_code = str(auth_code or "").strip()
        if len(normalized_auth_code) < 10:
            self.error = "授权码长度不能少于 10 个字符"
            return None
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE role='admin' LIMIT 1").fetchone()
            if row is None:
                self.error = "管理员账号不存在"
                return None
            connection.execute(
                """UPDATE users SET admin_pop_auth_code=?, admin_pop_auth_code_hash=NULL,
                admin_pop_auth_code_updated_at=?,
                updated_at=? WHERE id=?""",
                (normalized_auth_code, utc_now(), utc_now(), row["id"]),
            )
            row = connection.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
        return _public_user(row)

    def get_admin_pop_auth_code(self) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT admin_pop_auth_code, admin_pop_auth_code_hash,
                admin_pop_auth_code_updated_at FROM users WHERE role='admin' LIMIT 1"""
            ).fetchone()
        if row is None:
            return {
                "configured": False,
                "admin_pop_auth_code": "",
                "legacy_hash_only": False,
                "updated_at": None,
            }
        plaintext = str(row["admin_pop_auth_code"] or "")
        return {
            "configured": bool(plaintext or row["admin_pop_auth_code_hash"]),
            "admin_pop_auth_code": plaintext,
            "legacy_hash_only": bool(not plaintext and row["admin_pop_auth_code_hash"]),
            "updated_at": row["admin_pop_auth_code_updated_at"],
        }

    def verify_user_pop_auth_code(self, user_id: int, auth_code: str) -> bool:
        now = datetime.now(UTC)
        row = self._get_user_with_secret(user_id)
        if row is None or row["status"] != "active" or not row["pop_enabled"]:
            return False
        locked_until = _parse_datetime(row["pop_locked_until"])
        if locked_until and locked_until > now:
            return False
        if row["user_auth_code_hash"] and verify_admin_password(auth_code, row["user_auth_code_hash"]):
            with self.database.transaction() as connection:
                connection.execute(
                    """UPDATE users SET pop_failed_attempts=0, pop_locked_until=NULL,
                    last_pop_login_at=?, updated_at=? WHERE id=?""",
                    (now.isoformat(), now.isoformat(), user_id),
                )
            return True

        with self.database.transaction() as connection:
            attempts = int(row["pop_failed_attempts"]) + 1
            locked_value = (now + timedelta(minutes=15)).isoformat() if attempts >= 5 else None
            connection.execute(
                """UPDATE users SET pop_failed_attempts=?, pop_locked_until=?, updated_at=? WHERE id=?""",
                (attempts, locked_value, now.isoformat(), user_id),
            )
        return False

    def verify_admin_pop_auth_code(self, auth_code: str) -> bool:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT admin_pop_auth_code, admin_pop_auth_code_hash
                FROM users WHERE role='admin' LIMIT 1"""
            ).fetchone()
        if row is None:
            return False
        plaintext = str(row["admin_pop_auth_code"] or "")
        if plaintext:
            return hmac.compare_digest(str(auth_code or ""), plaintext)
        return bool(
            row["admin_pop_auth_code_hash"]
            and verify_admin_password(auth_code, row["admin_pop_auth_code_hash"])
        )

    def create_api_key(self, user_id: int, name: str) -> dict[str, Any]:
        api_key = "xmk_" + secrets.token_urlsafe(32)
        current = utc_now()
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id, role, status FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if user is None or user["role"] != "user" or user["status"] != "active":
                raise ValueError("用户不可用")
            inserted = connection.execute(
                """INSERT INTO user_api_keys
                (user_id, name, key_prefix, key_hash, enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?) RETURNING id""",
                (user_id, name.strip(), api_key[:12], hash_api_key(api_key), current),
            )
            key_id = int(inserted.fetchone()["id"])
            row = connection.execute("SELECT * FROM user_api_keys WHERE id=?", (key_id,)).fetchone()
        return _public_api_key(row, plaintext=api_key)

    def list_api_keys(self, user_id: int) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT id, user_id, name, key_prefix, enabled, last_used_at, created_at, revoked_at
                FROM user_api_keys WHERE user_id=? ORDER BY id DESC""",
                (user_id,),
            ).fetchall()
        return [_public_api_key(row) for row in rows]

    def revoke_api_key(self, user_id: int, key_id: int) -> bool:
        with self.database.transaction() as connection:
            result = connection.execute(
                """UPDATE user_api_keys SET enabled=0, revoked_at=?
                WHERE id=? AND user_id=? AND revoked_at IS NULL""",
                (utc_now(), key_id, user_id),
            )
        return result.rowcount > 0

    def authenticate_api_key(self, api_key: str) -> dict[str, Any] | None:
        if not api_key:
            _authenticated_user_id.set(None)
            return None
        key_hash = hash_api_key(api_key)
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT k.*, u.username, u.role, u.status, u.pop_enabled
                FROM user_api_keys k JOIN users u ON u.id=k.user_id
                WHERE k.key_hash=? AND k.enabled=1 AND k.revoked_at IS NULL AND u.status='active'""",
                (key_hash,),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE user_api_keys SET last_used_at=? WHERE id=?",
                    (utc_now(), row["id"]),
                )
        if row is None:
            _authenticated_user_id.set(None)
            return None
        _authenticated_user_id.set(int(row["user_id"]))
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "username": row["username"],
            "role": row["role"],
        }

    def reserve_mailbox_credit(self, user_id: int, reference_id: str) -> int:
        current = utc_now()
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id, role, status, credit_balance FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if user is None or user["role"] != "user" or user["status"] != "active":
                raise ValueError("USER_UNAVAILABLE")

            pending = connection.execute(
                """SELECT amount FROM credit_transactions
                WHERE user_id=? AND type='consume' AND status='pending'
                AND reference_type='mailbox' AND reference_id=?
                ORDER BY id DESC LIMIT 1""",
                (user_id, reference_id),
            ).fetchone()
            if pending is not None:
                return -int(pending["amount"])

            rule = connection.execute(
                "SELECT cost_points FROM credit_rules WHERE operation='create_mailbox'"
            ).fetchone()
            cost = int(rule["cost_points"]) if rule is not None else 0
            result = connection.execute(
                """UPDATE users SET credit_balance=credit_balance-?, updated_at=?
                WHERE id=? AND credit_balance>=?""",
                (cost, current, user_id, cost),
            )
            if result.rowcount != 1:
                raise ValueError("INSUFFICIENT_CREDITS")
            updated = connection.execute(
                "SELECT credit_balance FROM users WHERE id=?", (user_id,)
            ).fetchone()
            connection.execute(
                """INSERT INTO credit_transactions
                (user_id, type, status, amount, balance_after, reference_type, reference_id, remark, created_at)
                VALUES (?, 'consume', 'pending', ?, ?, 'mailbox', ?, '创建邮箱预扣积分', ?)""",
                (user_id, -cost, updated["credit_balance"], reference_id, current),
            )
        return cost

    def confirm_mailbox_credit(self, user_id: int, reference_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE credit_transactions SET status='completed'
                WHERE user_id=? AND type='consume' AND status='pending'
                AND reference_type='mailbox' AND reference_id=?""",
                (user_id, reference_id),
            )

    def refund_mailbox_credit(self, user_id: int, reference_id: str) -> None:
        current = utc_now()
        with self.database.transaction() as connection:
            pending = connection.execute(
                """SELECT id, amount FROM credit_transactions
                WHERE user_id=? AND type='consume' AND status='pending'
                AND reference_type='mailbox' AND reference_id=?
                ORDER BY id DESC LIMIT 1""",
                (user_id, reference_id),
            ).fetchone()
            if pending is None:
                return
            refund_amount = -int(pending["amount"])
            result = connection.execute(
                """UPDATE users SET credit_balance=credit_balance+?, updated_at=?
                WHERE id=?""",
                (refund_amount, current, user_id),
            )
            if result.rowcount != 1:
                raise ValueError("USER_UNAVAILABLE")
            updated = connection.execute(
                "SELECT credit_balance FROM users WHERE id=?", (user_id,)
            ).fetchone()
            connection.execute(
                """UPDATE credit_transactions SET status='reversed'
                WHERE id=? AND status='pending'""",
                (pending["id"],),
            )
            connection.execute(
                """INSERT INTO credit_transactions
                (user_id, type, status, amount, balance_after, reference_type, reference_id, remark, created_at)
                VALUES (?, 'refund', 'completed', ?, ?, 'mailbox', ?, '邮箱创建失败退款', ?)""",
                (user_id, refund_amount, updated["credit_balance"], reference_id, current),
            )

    def get_credit_rule(self) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT operation, cost_points, initial_user_points, updated_by, updated_at FROM credit_rules WHERE operation='create_mailbox'"
            ).fetchone()
        return dict(row)

    def update_credit_rule(self, *, cost_points: int, initial_user_points: int, admin_user_id: int) -> dict[str, Any]:
        current = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO credit_rules(operation, cost_points, initial_user_points, updated_by, updated_at)
                VALUES ('create_mailbox', ?, ?, ?, ?)
                ON CONFLICT(operation) DO UPDATE SET cost_points=excluded.cost_points,
                initial_user_points=excluded.initial_user_points, updated_by=excluded.updated_by,
                updated_at=excluded.updated_at""",
                (cost_points, initial_user_points, admin_user_id, current),
            )
            row = connection.execute(
                "SELECT operation, cost_points, initial_user_points, updated_by, updated_at FROM credit_rules WHERE operation='create_mailbox'"
            ).fetchone()
        return dict(row)

    def get_credits(self, user_id: int, limit: int = 20) -> dict[str, Any] | None:
        with self.database.read() as connection:
            user = connection.execute(
                "SELECT id, credit_balance FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if user is None:
                return None
            rows = connection.execute(
                """SELECT id, type, status, amount, balance_after, reference_type,
                reference_id, remark, created_at FROM credit_transactions
                WHERE user_id=? ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return {"user_id": user_id, "balance": user["credit_balance"], "transactions": [dict(row) for row in rows]}

    def adjust_credits(self, *, user_id: int, amount: int, reason: str, admin_user_id: int) -> dict[str, Any] | None:
        if amount == 0:
            self.error = "积分调整数量不能为 0"
            return None
        current = utc_now()
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id, role, credit_balance FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if user is None or user["role"] != "user":
                self.error = "普通用户不存在"
                return None
            result = connection.execute(
                """UPDATE users SET credit_balance=credit_balance + ?, updated_at=?
                WHERE id=? AND credit_balance + ? >= 0""",
                (amount, current, user_id, amount),
            )
            if result.rowcount != 1:
                self.error = "积分余额不能为负数"
                return None
            updated = connection.execute(
                "SELECT credit_balance FROM users WHERE id=?", (user_id,)
            ).fetchone()
            inserted = connection.execute(
                """INSERT INTO credit_transactions
                (user_id, type, status, amount, balance_after, reference_type, reference_id, remark, created_at)
                VALUES (?, 'admin_adjust', 'completed', ?, ?, 'admin', ?, ?, ?) RETURNING id""",
                (user_id, amount, updated["credit_balance"], str(admin_user_id), reason.strip(), current),
            )
            transaction_id = int(inserted.fetchone()["id"])
        return {
            "user_id": user_id,
            "amount": amount,
            "balance_after": updated["credit_balance"],
            "transaction_id": transaction_id,
            "remark": reason.strip(),
        }

    def list_credit_transactions(self, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT id, user_id, type, status, amount, balance_after, reference_type,
                reference_id, remark, created_at FROM credit_transactions
                WHERE user_id=? ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_user_mailboxes(self, user_id: int, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT m.id, m.address, m.purpose, m.source, m.status,
                m.verification_status, m.pop_enabled, m.created_at, m.expires_at,
                m.updated_at, d.domain
                FROM mailboxes m LEFT JOIN mail_domains d ON d.id=m.domain_id
                WHERE m.owner_user_id=? ORDER BY m.created_at DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            ).fetchall()
        return [{**dict(row), "pop_enabled": bool(row["pop_enabled"])} for row in rows]

    def audit_admin(
        self,
        *,
        admin_user_id: int,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: str = "",
        request_id: str = "",
        source_ip: str = "",
    ) -> None:
        admin = self.get_user(admin_user_id)
        username = admin["username"] if admin else "admin"
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO admin_audit_logs
                (admin_user_id, username, action, target_type, target_id, detail, request_id, source_ip, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    admin_user_id,
                    username,
                    action,
                    target_type,
                    target_id,
                    detail[:1000],
                    request_id[:100],
                    source_ip[:100],
                    utc_now(),
                ),
            )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = ["UserRepository", "get_authenticated_user_id", "hash_api_key"]
