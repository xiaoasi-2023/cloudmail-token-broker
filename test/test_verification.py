from datetime import UTC, datetime, timedelta

from app.gateway.business_models import MailMessage
from app.gateway.verification import extract_verification_code


def extract(purpose: str, subject: str, body: str, *, seconds: int = 1) -> str:
    created = datetime.now(UTC)
    return extract_verification_code(
        [MailMessage(subject=subject, text=body, received_at=created + timedelta(seconds=seconds))],
        purpose=purpose,
        mailbox_created_at=created,
    )


def test_project_specific_verification_rules() -> None:
    assert extract("openai", "你的 ChatGPT 临时验证码", "输入此临时验证码以继续：624182") == "624182"
    assert extract("kiro", "Verify your AWS Builder ID", "Verification code: 736592") == "736592"
    assert extract("cursor", "注册 Cursor", "您的一次性验证码是：961941") == "961941"
    assert extract("grok", "NVK-5XZ xAI confirmation code", "Validate your email NVK-5XZ") == "NVK-5XZ"


def test_project_rules_reject_unrelated_years_and_wrong_formats() -> None:
    assert extract("openai", "New sign-in", "Time: June 22, 2026 at 7:27 AM") == ""
    assert extract("grok", "Claude security notice", "Copyright 2026, code 123456") == ""
    assert extract("cursor", "Cursor", "Reference number 202608") == ""


def test_old_messages_are_ignored_but_untimed_new_mailbox_messages_are_supported() -> None:
    created = datetime.now(UTC)
    old = MailMessage(text="输入此临时验证码以继续：111111", received_at=created - timedelta(minutes=1))
    untimed = MailMessage(text="输入此临时验证码以继续：222222")
    assert extract_verification_code([old, untimed], purpose="openai", mailbox_created_at=created) == "222222"


def test_html_style_noise_does_not_become_code() -> None:
    created = datetime.now(UTC)
    message = MailMessage(
        subject="Verify your AWS Builder ID",
        html="<style>.title{color:#555555}</style><p>Verification code: <b>483920</b></p>",
        received_at=created,
    )
    assert extract_verification_code([message], purpose="kiro", mailbox_created_at=created) == "483920"
