from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.gateway.business_models import MailMessage
from app.gateway.cloudmail_provider import CloudMailProviderRegistry
from app.gateway.database import GatewayDatabase
from app.gateway.database_business_store import DatabaseGatewayBusinessStore
from app.gateway.pop3_server import Pop3Mailbox, Pop3Principal
from app.gateway.user_repository import UserRepository


class Pop3GatewayProvider:
    """Bridge POP3 sessions to the user repository and CloudMail providers."""

    def __init__(
        self,
        database: GatewayDatabase,
        users: UserRepository,
        store: DatabaseGatewayBusinessStore,
        providers: CloudMailProviderRegistry,
    ) -> None:
        self.database = database
        self.users = users
        self.store = store
        self.providers = providers

    async def authenticate(self, username: str, password: str) -> Pop3Principal | None:
        address = _normalize_address(username)
        if not address or not password:
            return None

        if self.users.verify_admin_pop_auth_code(password):
            return Pop3Principal(self._admin_user_id(), is_admin=True)

        owner_id = self._mailbox_owner_id(address)
        if owner_id is None:
            return None
        if not self.users.verify_user_pop_auth_code(owner_id, password):
            return None
        return Pop3Principal(str(owner_id))

    async def resolve_mailbox(self, address: str) -> Pop3Mailbox | None:
        normalized = _normalize_address(address)
        if not normalized:
            return None
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT id, address, owner_user_id, instance_id, status,
                pop_enabled, expires_at, verification_status
                FROM mailboxes WHERE lower(address)=? LIMIT 1""",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return Pop3Mailbox(
            address=str(row["address"]),
            owner_user_id=row["owner_user_id"],
            provider_mailbox=dict(row),
            mailbox_id=str(row["id"]),
            status=str(row["status"]),
            pop_enabled=bool(row["pop_enabled"]),
            expires_at=_parse_datetime(row["expires_at"]),
        )

    async def list_messages(self, mailbox: Pop3Mailbox, *, size: int) -> Sequence[MailMessage]:
        instance_id = _instance_id(mailbox.provider_mailbox)
        if instance_id is None and mailbox.mailbox_id:
            with self.database.read() as connection:
                row = connection.execute(
                    "SELECT instance_id FROM mailboxes WHERE id=?",
                    (mailbox.mailbox_id,),
                ).fetchone()
            instance_id = int(row["instance_id"]) if row is not None else None
        if instance_id is None:
            raise RuntimeError("mailbox provider instance is missing")

        instance = self.store.get_instance(instance_id)
        if instance is None or not instance.enabled:
            raise RuntimeError("mailbox provider is unavailable")
        client = await self.providers.client_for(instance)
        return await client.list_messages(mailbox.address, size=size)

    def _mailbox_owner_id(self, address: str) -> int | None:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT u.id FROM mailboxes m JOIN users u ON u.id=m.owner_user_id
                WHERE lower(m.address)=? AND u.role='user' LIMIT 1""",
                (address,),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    def _admin_user_id(self) -> str:
        with self.database.read() as connection:
            row = connection.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        return str(row["id"]) if row is not None else "admin"


def _normalize_address(value: str) -> str:
    address = str(value or "").strip().lower()
    if len(address) > 320 or address.count("@") != 1:
        return ""
    local, domain = address.split("@", 1)
    if not local or not domain or any(char.isspace() for char in address):
        return ""
    return address


def _instance_id(value: Any) -> int | None:
    if not isinstance(value, dict) or value.get("instance_id") is None:
        return None
    try:
        return int(value["instance_id"])
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = ["Pop3GatewayProvider"]
