from __future__ import annotations

import pytest

from app.config import Settings


def set_cloudmail_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDMAIL_BASE_URL", "https://mail.example.com")
    monkeypatch.setenv("CLOUDMAIL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("CLOUDMAIL_ADMIN_PASSWORD", "cloudmail-password-secret")
    monkeypatch.delenv("BROKER_ADMIN_KEY", raising=False)
    monkeypatch.delenv("BROKER_CLIENT_KEYS_JSON", raising=False)
    monkeypatch.delenv("BROKER_CLIENT_KEYS", raising=False)


def test_public_access_allows_empty_broker_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    set_cloudmail_environment(monkeypatch)
    monkeypatch.setenv("BROKER_PUBLIC_ACCESS", "true")

    settings = Settings.from_env()

    assert settings.broker_public_access is True
    assert settings.broker_admin_key == ""
    assert settings.broker_client_keys == {}


def test_private_access_still_requires_client_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    set_cloudmail_environment(monkeypatch)
    monkeypatch.setenv("BROKER_PUBLIC_ACCESS", "false")

    with pytest.raises(RuntimeError, match="BROKER_CLIENT_KEYS_JSON"):
        Settings.from_env()
