from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


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


def _client_keys() -> dict[str, str]:
    raw = _env("BROKER_CLIENT_KEYS_JSON") or _env("BROKER_CLIENT_KEYS")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BROKER_CLIENT_KEYS_JSON 必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("BROKER_CLIENT_KEYS_JSON 必须是 JSON 对象")
    result: dict[str, str] = {}
    for client_id, key in parsed.items():
        clean_id = str(client_id or "").strip()
        clean_key = str(key or "").strip()
        if clean_id and clean_key:
            result[clean_id] = clean_key
    return result


@dataclass(frozen=True)
class Settings:
    cloudmail_base_url: str = ""
    cloudmail_admin_email: str = ""
    cloudmail_admin_password: str = ""
    broker_admin_key: str = ""
    broker_client_keys: dict[str, str] = field(default_factory=dict)
    broker_public_access: bool = False
    token_cache_seconds: int = 1500
    token_refresh_skew_seconds: int = 120
    request_timeout_seconds: int = 15
    cloudmail_verify_tls: bool = True
    cloudmail_proxy: str = ""
    token_rate_limit_per_minute: int = 60
    refresh_rate_limit_per_minute: int = 10
    admin_rate_limit_per_minute: int = 2
    log_level: str = "INFO"
    gateway_enabled: bool = False
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
            cloudmail_base_url=_env("CLOUDMAIL_BASE_URL").rstrip("/"),
            cloudmail_admin_email=_env("CLOUDMAIL_ADMIN_EMAIL"),
            cloudmail_admin_password=_env("CLOUDMAIL_ADMIN_PASSWORD"),
            broker_admin_key=_env("BROKER_ADMIN_KEY"),
            broker_client_keys=_client_keys(),
            broker_public_access=_bool_env("BROKER_PUBLIC_ACCESS", False),
            token_cache_seconds=_int_env("TOKEN_CACHE_SECONDS", 1500, 60, 86400),
            token_refresh_skew_seconds=_int_env("TOKEN_REFRESH_SKEW_SECONDS", 120, 0, 3600),
            request_timeout_seconds=_int_env("REQUEST_TIMEOUT_SECONDS", 15, 1, 120),
            cloudmail_verify_tls=_bool_env("CLOUDMAIL_VERIFY_TLS", True),
            cloudmail_proxy=_env("CLOUDMAIL_PROXY"),
            token_rate_limit_per_minute=_int_env("TOKEN_RATE_LIMIT_PER_MINUTE", 60, 1, 10000),
            refresh_rate_limit_per_minute=_int_env("REFRESH_RATE_LIMIT_PER_MINUTE", 10, 1, 1000),
            admin_rate_limit_per_minute=_int_env("ADMIN_RATE_LIMIT_PER_MINUTE", 2, 1, 100),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            gateway_enabled=_bool_env("GATEWAY_ENABLED", False),
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
        missing: list[str] = []
        legacy_values = (
            self.cloudmail_base_url,
            self.cloudmail_admin_email,
            self.cloudmail_admin_password,
        )
        if any(legacy_values) and not all(legacy_values):
            missing.extend(
                name
                for name, value in (
                    ("CLOUDMAIL_BASE_URL", self.cloudmail_base_url),
                    ("CLOUDMAIL_ADMIN_EMAIL", self.cloudmail_admin_email),
                    ("CLOUDMAIL_ADMIN_PASSWORD", self.cloudmail_admin_password),
                )
                if not value
            )
        if not self.broker_public_access and not self.broker_client_keys:
            missing.append("BROKER_CLIENT_KEYS_JSON")
        if missing:
            raise RuntimeError(f"缺少必要环境变量: {', '.join(missing)}")
        if self.broker_admin_key and len(self.broker_admin_key) < 32:
            raise RuntimeError("BROKER_ADMIN_KEY 长度不能少于 32 个字符")
        short_client_ids = [
            client_id
            for client_id, key in self.broker_client_keys.items()
            if len(key) < 32
        ]
        if short_client_ids:
            raise RuntimeError(
                "以下客户端的 Broker Client Key 长度少于 32 个字符: "
                + ", ".join(sorted(short_client_ids))
            )
        if len(set(self.broker_client_keys.values())) != len(self.broker_client_keys):
            raise RuntimeError("BROKER_CLIENT_KEYS_JSON 中不同客户端不能共用同一个密钥")
        if self.broker_admin_key and self.broker_admin_key in self.broker_client_keys.values():
            raise RuntimeError("BROKER_ADMIN_KEY 不能与 Broker Client Key 相同")
        if self.token_refresh_skew_seconds >= self.token_cache_seconds:
            raise RuntimeError("TOKEN_REFRESH_SKEW_SECONDS 必须小于 TOKEN_CACHE_SECONDS")
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

    @property
    def legacy_cloudmail_configured(self) -> bool:
        return bool(
            self.cloudmail_base_url
            and self.cloudmail_admin_email
            and self.cloudmail_admin_password
        )
