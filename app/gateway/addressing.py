from __future__ import annotations

import re
import secrets
import string

from app.gateway.business_errors import GatewayBusinessError


_INVALID_PREFIX = re.compile(r"[^a-z0-9]+")
_RESERVED_PREFIXES = {"admin", "administrator", "postmaster", "root", "support", "system"}
_ALPHABET = string.ascii_lowercase + string.digits


def normalize_domain(value: str) -> str:
    return value.strip().lower().lstrip("@").rstrip(".")


def sanitize_prefix(value: str, default: str = "mail") -> str:
    prefix = _INVALID_PREFIX.sub("", value.strip().lower())[:16]
    if not prefix or prefix in _RESERVED_PREFIXES:
        return default
    return prefix


def generate_mailbox_address(prefix: str, domain: str, random_length: int = 12) -> str:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain or "." not in normalized_domain:
        raise GatewayBusinessError("DOMAIN_NOT_ALLOWED", "邮箱域名格式无效", 400)
    safe_prefix = sanitize_prefix(prefix)
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(random_length))
    return f"{safe_prefix}-{suffix}@{normalized_domain}"


def generate_mailbox_password(length: int = 24) -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
