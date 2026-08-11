from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.gateway.business_models import (
    CloudMailInstanceConfig,
    IdempotencyRecord,
    MailDomainConfig,
    MailboxRecord,
)
from app.gateway.crypto import SecretCipher
from app.gateway.database import GatewayDatabase
from app.gateway.user_repository import UserRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class DatabaseGatewayBusinessStore:
    """将邮箱网关业务协议适配到 Gateway PostgreSQL 数据表。"""

    def __init__(
        self,
        database: GatewayDatabase,
        cipher: SecretCipher,
        *,
        domain_failure_threshold: int = 3,
        domain_cooldown_seconds: int = 300,
    ) -> None:
        self.database = database
        self.cipher = cipher
        self.domain_failure_threshold = max(1, domain_failure_threshold)
        self.domain_cooldown_seconds = max(1, domain_cooldown_seconds)
        self.users = UserRepository(database)

    def list_domains(self) -> list[MailDomainConfig]:
        with self.database.read() as connection:
            rows = connection.execute("SELECT * FROM mail_domains ORDER BY id").fetchall()
        return [
            MailDomainConfig(
                id=int(row["id"]),
                instance_id=int(row["instance_id"]),
                domain=str(row["domain"]),
                weight=int(row["weight"]),
                enabled=bool(row["enabled"]),
                status=str(row["status"]),
                cooldown_until=_parse_time(row["cooldown_until"]),
            )
            for row in rows
        ]

    def get_instance(self, instance_id: int) -> CloudMailInstanceConfig | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM cloudmail_instances WHERE id = ?",
                (instance_id,),
            ).fetchone()
        if row is None:
            return None
        return CloudMailInstanceConfig(
            id=int(row["id"]),
            base_url=str(row["base_url"]),
            admin_email=str(row["admin_email"]),
            admin_password=self.cipher.decrypt(str(row["admin_password_encrypted"])),
            proxy_url=str(row["proxy_url"]),
            verify_tls=bool(row["verify_tls"]),
            enabled=bool(row["enabled"]),
            health_status=str(row["health_status"]),
        )

    def get_mailbox(self, mailbox_id: str) -> MailboxRecord | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
        if row is None:
            return None
        expires_at = _parse_time(row["expires_at"])
        if expires_at is None:
            expires_at = _now()
        created_at = _parse_time(row["created_at"])
        if created_at is None:  # pragma: no cover - 数据库字段为 NOT NULL
            created_at = _now()
        return MailboxRecord(
            id=str(row["id"]),
            address=str(row["address"]),
            domain_id=int(row["domain_id"]),
            instance_id=int(row["instance_id"]),
            purpose=str(row["purpose"]),
            source=str(row["source"]),
            status=str(row["status"]),
            verification_status=str(row["verification_status"]),
            verification_code=str(row["verification_code"]),
            provider_reference=str(row["provider_reference"]),
            created_at=created_at,
            expires_at=expires_at,
            owner_user_id=int(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
        )

    def save_mailbox(
        self,
        mailbox: MailboxRecord,
        idempotency: IdempotencyRecord | None = None,
    ) -> None:
        now = _now().isoformat()
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO mailboxes
                (id, address, owner_user_id, domain_id, instance_id, purpose, source, status,
                 verification_status, verification_code, provider_reference,
                 created_at, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mailbox.id,
                    mailbox.address,
                    mailbox.owner_user_id,
                    mailbox.domain_id,
                    mailbox.instance_id,
                    mailbox.purpose,
                    mailbox.source,
                    mailbox.status,
                    mailbox.verification_status,
                    mailbox.verification_code,
                    mailbox.provider_reference,
                    mailbox.created_at.isoformat(),
                    mailbox.expires_at.isoformat(),
                    now,
                ),
            )
            if idempotency:
                connection.execute(
                    """INSERT INTO idempotency_records
                    (idempotency_key, user_id, request_hash, mailbox_id, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        idempotency.key,
                        idempotency.user_id,
                        idempotency.request_hash,
                        idempotency.mailbox_id,
                        now,
                        idempotency.expires_at.isoformat(),
                    ),
                )

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        now = _now()
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM idempotency_records WHERE expires_at <= ?", (now.isoformat(),))
            row = connection.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        expires_at = _parse_time(row["expires_at"])
        if expires_at is None:
            return None
        return IdempotencyRecord(
            key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            mailbox_id=str(row["mailbox_id"]),
            expires_at=expires_at,
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
        )

    def mark_domain_success(self, domain_id: int) -> None:
        now = _now().isoformat()
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE mail_domains
                SET status='healthy', failure_count=0, cooldown_until=NULL,
                    success_count=success_count+1, last_used_at=?, updated_at=?
                WHERE id=?""",
                (now, now, domain_id),
            )

    def mark_domain_failure(self, domain_id: int, error_code: str) -> None:
        del error_code  # 错误码由请求日志记录，域名表只维护健康统计。
        now = _now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT failure_count FROM mail_domains WHERE id = ?",
                (domain_id,),
            ).fetchone()
            if row is None:
                return
            failure_count = int(row["failure_count"]) + 1
            cooling = failure_count >= self.domain_failure_threshold
            cooldown_until = (
                (now + timedelta(seconds=self.domain_cooldown_seconds)).isoformat() if cooling else None
            )
            connection.execute(
                """UPDATE mail_domains
                SET status=?, failure_count=?, failure_total=failure_total+1,
                    cooldown_until=?, updated_at=? WHERE id=?""",
                (
                    "cooldown" if cooling else "unknown",
                    failure_count,
                    cooldown_until,
                    now.isoformat(),
                    domain_id,
                ),
            )

    def set_verification_status(
        self,
        mailbox_id: str,
        status: str,
        verification_code: str = "",
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE mailboxes
                SET verification_status=?, verification_code=?, updated_at=?
                WHERE id=?""",
                (status, verification_code, _now().isoformat(), mailbox_id),
            )

    def set_mailbox_status(self, mailbox_id: str, status: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE mailboxes SET status=?, updated_at=? WHERE id=?",
                (status, _now().isoformat(), mailbox_id),
            )

    def reserve_mailbox_credit(self, user_id: int, reference_id: str) -> int:
        return self.users.reserve_mailbox_credit(user_id, reference_id)

    def confirm_mailbox_credit(self, user_id: int, reference_id: str) -> None:
        self.users.confirm_mailbox_credit(user_id, reference_id)

    def refund_mailbox_credit(self, user_id: int, reference_id: str) -> None:
        self.users.refund_mailbox_credit(user_id, reference_id)
