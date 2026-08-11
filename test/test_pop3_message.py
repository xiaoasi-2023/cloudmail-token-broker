from __future__ import annotations

from datetime import UTC, datetime

from app.gateway.business_models import MailMessage
from app.gateway.pop3_message import dot_stuff, message_uidl, render_mail_message


def test_rendered_message_has_rfc822_headers_and_crlf() -> None:
    message = MailMessage(
        subject="验证码\n不要注入",
        text="第一行\n.第二行\r第三行",
        received_at=datetime(2026, 8, 11, 8, 30, tzinfo=UTC),
        raw={
            "emailId": "cloud-123",
            "fromEmail": "sender@example.com",
            "toEmail": "user@example.com",
        },
    )

    rendered = render_mail_message(message, "user@example.com")
    decoded = rendered.data.decode("utf-8")

    assert rendered.uidl == "cloud-123"
    assert "From: sender@example.com\r\n" in decoded
    assert "To: user@example.com\r\n" in decoded
    assert "Subject:" in decoded
    assert "Date: Tue, 11 Aug 2026 08:30:00 +0000\r\n" in decoded
    assert "Message-ID: <cloud-123@example.com>\r\n" in decoded
    assert "Content-Type: text/plain; charset=utf-8\r\n" in decoded
    assert "\r\n\r\n第一行\r\n.第二行\r\n第三行\r\n" in decoded
    assert b"\n" not in rendered.data.replace(b"\r\n", b"")
    assert rendered.size == len(rendered.data)


def test_uidl_without_provider_id_is_stable_and_changes_with_message_content() -> None:
    first = MailMessage(subject="Hello", text="one", received_at=datetime(2026, 8, 11, tzinfo=UTC))
    same = MailMessage(subject="Hello", text="one", received_at=datetime(2026, 8, 11, tzinfo=UTC))
    changed = MailMessage(subject="Hello", text="two", received_at=datetime(2026, 8, 11, tzinfo=UTC))

    assert message_uidl(first, "user@example.com") == message_uidl(same, "user@example.com")
    assert message_uidl(first, "user@example.com") != message_uidl(changed, "user@example.com")
    assert message_uidl(first, "user@example.com").startswith("cm-")


def test_multipart_message_and_top_preserve_headers_and_requested_body_lines() -> None:
    plain = render_mail_message(
        MailMessage(subject="Plain", text="plain one\nplain two"),
        "user@example.com",
    )
    top = plain.top(1).decode("utf-8")
    assert "plain one" in top
    assert "plain two" not in top

    rendered = render_mail_message(
        MailMessage(
            subject="Multipart",
            text="plain one\nplain two",
            html="<p>html</p>",
            raw={"messageId": "original@example.com"},
        ),
        "user@example.com",
    )

    full = rendered.data.decode("utf-8")
    assert "Content-Type: multipart/alternative;" in full
    assert "Message-ID: <original@example.com>\r\n" in full


def test_dot_stuffing_and_crlf_normalization() -> None:
    assert dot_stuff(b"one\n.two\rthree") == b"one\r\n..two\r\nthree\r\n"
