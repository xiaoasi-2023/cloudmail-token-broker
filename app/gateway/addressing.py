from __future__ import annotations

import re
import secrets
import string

from faker import Faker

from app.gateway.business_errors import GatewayBusinessError


_INVALID_PREFIX = re.compile(r"[^a-z0-9]+")
_INVALID_NAME_PART = re.compile(r"[^A-Za-z]+")
_RESERVED_PREFIXES = {"admin", "administrator", "postmaster", "root", "support", "system"}
_ALPHABET = string.ascii_lowercase + string.digits
_FAKER = Faker("en_US")
_FIRST_NAMES = (
    "Daniel", "Ben", "James", "John", "Michael", "David", "Chris", "Ryan", "Kevin", "Brian",
    "Matthew", "Andrew", "Jason", "Justin", "Eric", "Adam", "Mark", "Paul", "Steven", "Thomas",
    "Robert", "William", "Joseph", "Charles", "Anthony", "Joshua", "Nicholas", "Jonathan", "Aaron", "Nathan",
    "Samuel", "Dylan", "Ethan", "Lucas", "Mason", "Logan", "Owen", "Caleb", "Noah", "Liam",
    "Emma", "Olivia", "Ava", "Sophia", "Mia", "Isabella", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Emily", "Abigail", "Elizabeth", "Sofia", "Avery", "Ella", "Scarlett", "Grace", "Chloe", "Victoria",
    "Riley", "Aria", "Lily", "Aubrey", "Zoey", "Penelope", "Layla", "Nora", "Camila", "Hannah",
    "Alex", "Sam", "Taylor", "Jordan", "Casey", "Morgan", "Jamie", "Cameron", "Drew", "Reese",
)
_LAST_NAMES = (
    "Carter", "Evans", "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson",
    "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia",
    "Martinez", "Robinson", "Clark", "Rodriguez", "Lewis", "Lee", "Walker", "Hall", "Allen", "Young",
    "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Hill", "Ramirez", "Campbell",
    "Mitchell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Torres", "Parker", "Collins", "Edwards",
    "Stewart", "Flores", "Morris", "Nguyen", "Murphy", "Rivera", "Cook", "Rogers", "Morgan", "Peterson",
    "Cooper", "Reed", "Bailey", "Bell", "Gomez", "Kelly", "Howard", "Ward", "Cox", "Diaz",
    "Richardson", "Wood", "Watson", "Brooks", "Bennett", "Gray", "James", "Reyes", "Cruz", "Hughes",
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

    random_name = _random_human_name()
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


def _random_human_name() -> str:
    first_name = _INVALID_NAME_PART.sub("", _FAKER.first_name())
    last_name = _INVALID_NAME_PART.sub("", _FAKER.last_name())
    if first_name and last_name:
        return first_name + last_name
    return secrets.choice(_FIRST_NAMES) + secrets.choice(_LAST_NAMES)


def _random_text(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_mailbox_password(length: int = 24) -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
