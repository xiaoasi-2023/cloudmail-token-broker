from __future__ import annotations

import re
import secrets
import string

from app.gateway.business_errors import GatewayBusinessError


_INVALID_PREFIX = re.compile(r"[^a-z0-9]+")
_RESERVED_PREFIXES = {"admin", "administrator", "postmaster", "root", "support", "system"}
_ALPHABET = string.ascii_lowercase + string.digits
_NAMES = (
    "alex", "alice", "amelia", "ava", "ben", "chloe", "daniel", "ella",
    "emma", "ethan", "eva", "grace", "henry", "ivy", "jack", "james",
    "leo", "liam", "lily", "lucas", "mia", "mila", "nina", "noah",
    "oliver", "olivia", "oscar", "ryan", "sophia", "theo", "william", "zoe",
)
ADDRESS_PATTERNS = {
    "name_digits_4",
    "name_digits_6",
    "name_random_6",
    "random_12",
    "legacy_prefix_random",
}


def normalize_domain(value: str) -> str:
    return value.strip().lower().lstrip("@").rstrip(".")


def sanitize_prefix(value: str, default: str = "mail") -> str:
    prefix = _INVALID_PREFIX.sub("", value.strip().lower())[:16]
    if not prefix or prefix in _RESERVED_PREFIXES:
        return default
    return prefix


def generate_mailbox_address(
    domain: str,
    *,
    pattern: str = "name_digits_4",
    name: str = "",
    prefix: str = "",
) -> str:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain or "." not in normalized_domain:
        raise GatewayBusinessError("DOMAIN_NOT_ALLOWED", "邮箱域名格式无效", 400)
    if pattern not in ADDRESS_PATTERNS:
        raise GatewayBusinessError("ADDRESS_PATTERN_INVALID", "邮箱用户名生成规则无效", 400)

    random_name = secrets.choice(_NAMES)
    base = sanitize_prefix(name or prefix, default=random_name)
    if pattern == "name_digits_4":
        local_part = base + _random_digits(4)
    elif pattern == "name_digits_6":
        local_part = base + _random_digits(6)
    elif pattern == "name_random_6":
        local_part = base + _random_text(6)
    elif pattern == "random_12":
        local_part = _random_text(12)
    else:
        local_part = f"{base}-{_random_text(12)}"
    return f"{local_part}@{normalized_domain}"


def _random_digits(length: int) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _random_text(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_mailbox_password(length: int = 24) -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
