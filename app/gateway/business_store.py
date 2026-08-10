from __future__ import annotations

from typing import Protocol

from app.gateway.business_models import (
    CloudMailInstanceConfig,
    IdempotencyRecord,
    MailDomainConfig,
    MailboxRecord,
)


class GatewayBusinessStore(Protocol):
    """业务服务依赖的持久化边界，SQLite 实现可在主入口接入。"""

    def list_domains(self) -> list[MailDomainConfig]: ...

    def get_instance(self, instance_id: int) -> CloudMailInstanceConfig | None: ...

    def get_mailbox(self, mailbox_id: str) -> MailboxRecord | None: ...

    def save_mailbox(
        self,
        mailbox: MailboxRecord,
        idempotency: IdempotencyRecord | None = None,
    ) -> None: ...

    def get_idempotency(self, key: str) -> IdempotencyRecord | None: ...

    def mark_domain_success(self, domain_id: int) -> None: ...

    def mark_domain_failure(self, domain_id: int, error_code: str) -> None: ...

    def set_verification_status(self, mailbox_id: str, status: str) -> None: ...

    def set_mailbox_status(self, mailbox_id: str, status: str) -> None: ...
