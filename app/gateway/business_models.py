from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CloudMailInstanceConfig:
    id: int
    base_url: str
    admin_email: str
    admin_password: str
    proxy_url: str = ""
    verify_tls: bool = True
    enabled: bool = True
    health_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class MailDomainConfig:
    id: int
    instance_id: int
    domain: str
    weight: int = 100
    enabled: bool = True
    status: str = "unknown"
    cooldown_until: datetime | None = None


@dataclass(slots=True)
class MailboxRecord:
    id: str
    address: str
    domain_id: int
    instance_id: int
    purpose: str
    source: str
    provider_reference: str
    created_at: datetime
    expires_at: datetime
    status: str = "active"
    verification_status: str = "pending"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    request_hash: str
    mailbox_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MailMessage:
    subject: str = ""
    text: str = ""
    html: str = ""
    code: str = ""
    received_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
