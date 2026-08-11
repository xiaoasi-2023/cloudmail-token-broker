from __future__ import annotations

import pytest

from app.config import Settings


def set_gateway_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://gateway:test@127.0.0.1:5432/gateway_test")
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "data-encryption-key-for-tests-123456")
    monkeypatch.setenv("MAILBOX_SESSION_SECRET", "mailbox-session-secret-for-tests-12345")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-password")
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)


def test_gateway_uses_only_gateway_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)

    settings = Settings.from_env()

    assert settings.gateway_enabled is True
    assert settings.database_url == "postgresql://gateway:test@127.0.0.1:5432/gateway_test"
    assert settings.request_timeout_seconds == 15
    assert settings.admin_login_rate_limit_per_minute == 10


def test_gateway_rejects_missing_required_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")

    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY"):
        Settings.from_env()


def test_gateway_rejects_placeholder_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)
    monkeypatch.setenv("MAILBOX_SESSION_SECRET", "replace-with-at-least-48-byte-secret")

    with pytest.raises(RuntimeError, match="MAILBOX_SESSION_SECRET"):
        Settings.from_env()


def test_gateway_rejects_non_postgresql_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/gateway.db")

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings.from_env()


def test_registration_requires_complete_smtp_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)
    monkeypatch.setenv("USER_REGISTRATION_ENABLED", "true")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        Settings.from_env()


def test_registration_smtp_configuration_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    set_gateway_environment(monkeypatch)
    monkeypatch.setenv("USER_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.163.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "notice@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-authorization-code")
    monkeypatch.setenv("SMTP_FROM", "notice@example.com")
    monkeypatch.setenv("SMTP_TLS", "true")

    settings = Settings.from_env()

    assert settings.user_registration_enabled is True
    assert settings.smtp_host == "smtp.163.com"
    assert settings.smtp_port == 465
    assert settings.smtp_tls is True
