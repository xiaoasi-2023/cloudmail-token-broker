from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name, "true" if default else "false").lower()
    return value in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return lowered.startswith(("replace-with", "change-me", "your-"))


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: int = 15
    log_level: str = "INFO"
    gateway_enabled: bool = True
    gateway_database_path: str = "data/xiaoasi-mail.db"
    data_encryption_key: str = ""
    mailbox_session_secret: str = ""
    mailbox_session_ttl_seconds: int = 1800
    mailbox_create_rate_limit_per_minute: int = 120
    mailbox_poll_rate_limit_per_minute: int = 600
    admin_username: str = ""
    admin_password: str = ""
    admin_password_hash: str = ""
    admin_session_ttl_seconds: int = 28800
    admin_cookie_secure: bool = True
    admin_login_rate_limit_per_minute: int = 10
    admin_static_dir: str = "admin-web/dist"

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            request_timeout_seconds=_int_env("REQUEST_TIMEOUT_SECONDS", 15, 1, 120),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            gateway_enabled=_bool_env("GATEWAY_ENABLED", True),
            gateway_database_path=_env("GATEWAY_DATABASE_PATH", "data/xiaoasi-mail.db"),
            data_encryption_key=_env("DATA_ENCRYPTION_KEY"),
            mailbox_session_secret=_env("MAILBOX_SESSION_SECRET"),
            mailbox_session_ttl_seconds=_int_env("MAILBOX_SESSION_TTL_SECONDS", 1800, 300, 86400),
            mailbox_create_rate_limit_per_minute=_int_env(
                "MAILBOX_CREATE_RATE_LIMIT_PER_MINUTE", 120, 1, 10000
            ),
            mailbox_poll_rate_limit_per_minute=_int_env(
                "MAILBOX_POLL_RATE_LIMIT_PER_MINUTE", 600, 1, 50000
            ),
            admin_username=_env("ADMIN_USERNAME"),
            admin_password=_env("ADMIN_PASSWORD"),
            admin_password_hash=_env("ADMIN_PASSWORD_HASH"),
            admin_session_ttl_seconds=_int_env("ADMIN_SESSION_TTL_SECONDS", 28800, 300, 604800),
            admin_cookie_secure=_bool_env("ADMIN_COOKIE_SECURE", True),
            admin_login_rate_limit_per_minute=_int_env(
                "ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE", 10, 1, 1000
            ),
            admin_static_dir=_env("ADMIN_STATIC_DIR", "admin-web/dist"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.gateway_enabled:
            gateway_missing: list[str] = []
            if not self.gateway_database_path:
                gateway_missing.append("GATEWAY_DATABASE_PATH")
            if len(self.data_encryption_key.encode("utf-8")) < 32 or _is_placeholder(self.data_encryption_key):
                gateway_missing.append("DATA_ENCRYPTION_KEY（至少 32 字节）")
            if len(self.mailbox_session_secret.encode("utf-8")) < 32 or _is_placeholder(self.mailbox_session_secret):
                gateway_missing.append("MAILBOX_SESSION_SECRET（至少 32 字节）")
            if not self.admin_username:
                gateway_missing.append("ADMIN_USERNAME")
            if not self.admin_password and not self.admin_password_hash:
                gateway_missing.append("ADMIN_PASSWORD 或 ADMIN_PASSWORD_HASH")
            if self.admin_password and (len(self.admin_password) < 10 or _is_placeholder(self.admin_password)):
                raise RuntimeError("ADMIN_PASSWORD 长度不能少于 10 个字符")
            if self.admin_password_hash and not self.admin_password_hash.startswith("pbkdf2_sha256$"):
                raise RuntimeError("ADMIN_PASSWORD_HASH 格式无效")
            if gateway_missing:
                raise RuntimeError("启用邮箱网关时缺少配置: " + ", ".join(gateway_missing))
