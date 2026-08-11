from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import Header
from email.utils import format_datetime
from typing import Any

from app.gateway.business_models import MailMessage


_CRLF = b"\r\n"
_SAFE_UIDL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class Pop3RenderedMessage:
    """A single RFC822 message cached for one POP3 transaction."""

    uidl: str
    data: bytes
    headers: bytes
    body: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def top(self, body_lines: int) -> bytes:
        """Return the message headers and at most ``body_lines`` body lines."""

        if body_lines < 0:
            raise ValueError("body_lines must not be negative")

        if not self.body:
            return self.headers + _CRLF

        lines = self.body.split(_CRLF)
        if lines and lines[-1] == b"":
            lines.pop()
        selected = lines[:body_lines]
        body = _CRLF.join(selected)
        if body:
            body += _CRLF
        return self.headers + _CRLF + body


def render_mail_message(message: MailMessage, mailbox_address: str) -> Pop3RenderedMessage:
    """Convert the provider model into a small, deterministic RFC822 message."""

    uidl = message_uidl(message, mailbox_address)
    domain = mailbox_address.rsplit("@", 1)[-1] if "@" in mailbox_address else "localhost"
    from_value = _first_raw_text(
        message.raw,
        "from",
        "fromEmail",
        "from_email",
        "sender",
        "senderEmail",
        "sender_email",
        "fromAddress",
        "from_address",
    ) or f"CloudMail <no-reply@{domain}>"
    to_value = _first_raw_text(
        message.raw,
        "to",
        "toEmail",
        "to_email",
        "recipient",
        "recipientEmail",
        "recipient_email",
    ) or mailbox_address
    subject = _safe_header_text(message.subject or _first_raw_text(message.raw, "title"))
    received_at = _message_datetime(message)
    message_id = _message_id(message.raw, uidl, domain)

    body, content_type = _render_body(message, uidl)
    header_lines = [
        f"From: {_safe_header_text(from_value)}",
        f"To: {_safe_header_text(to_value)}",
        f"Subject: {str(Header(subject, 'utf-8'))}",
        f"Date: {format_datetime(received_at)}",
        f"Message-ID: {message_id}",
        f"Content-Type: {content_type}",
        "MIME-Version: 1.0",
    ]
    headers = _CRLF.join(line.encode("utf-8") for line in header_lines) + _CRLF
    data = headers + _CRLF + body
    return Pop3RenderedMessage(uidl=uidl, data=data, headers=headers, body=body)


def message_uidl(message: MailMessage, mailbox_address: str) -> str:
    """Return a stable POP UIDL, preferring CloudMail's stable message id."""

    raw = message.raw if isinstance(message.raw, dict) else {}
    for key in ("emailId", "email_id", "id", "uid", "uuid", "messageUid", "message_uid"):
        value = raw.get(key)
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate and _SAFE_UIDL.fullmatch(candidate):
            return candidate

    fingerprint = {
        "mailbox": mailbox_address.casefold(),
        "subject": message.subject,
        "text": message.text,
        "html": message.html,
        "code": message.code,
        "received_at": message.received_at.isoformat() if message.received_at else "",
        "raw": raw,
    }
    encoded = json.dumps(
        fingerprint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "cm-" + hashlib.sha256(encoded).hexdigest()[:40]


def dot_stuff(data: bytes) -> bytes:
    """Normalize a multi-line POP response and apply RFC 1939 dot-stuffing."""

    normalized = normalize_crlf_bytes(data)
    if not normalized.endswith(_CRLF):
        normalized += _CRLF
    lines = normalized.split(_CRLF)
    if lines and lines[-1] == b"":
        lines.pop()
    return b"".join((b"." if line.startswith(b".") else b"") + line + _CRLF for line in lines)


def normalize_crlf(value: str) -> bytes:
    return normalize_crlf_bytes(value.encode("utf-8", errors="replace"))


def normalize_crlf_bytes(value: bytes) -> bytes:
    return value.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", _CRLF)


def _render_body(message: MailMessage, uidl: str) -> tuple[bytes, str]:
    text = message.text or ""
    html = message.html or ""
    if text and html:
        boundary = f"=_cloudmail_{uidl}"
        content = (
            f"--{boundary}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Content-Transfer-Encoding: 8bit\r\n"
            "\r\n"
        ).encode("utf-8")
        content += _ensure_final_crlf(normalize_crlf(text))
        content += (
            f"\r\n--{boundary}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Content-Transfer-Encoding: 8bit\r\n"
            "\r\n"
        ).encode("utf-8")
        content += _ensure_final_crlf(normalize_crlf(html))
        content += f"\r\n--{boundary}--\r\n".encode("ascii")
        return content, f'multipart/alternative; boundary="{boundary}"'

    if html:
        return _ensure_final_crlf(normalize_crlf(html)), "text/html; charset=utf-8"
    return _ensure_final_crlf(normalize_crlf(text)), "text/plain; charset=utf-8"


def _message_datetime(message: MailMessage) -> datetime:
    value = message.received_at or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _message_id(raw: dict[str, Any], uidl: str, domain: str) -> str:
    value = _first_raw_text(raw, "messageId", "message_id", "internetMessageId", "internet_message_id")
    value = _safe_header_text(value)
    if value:
        return value if value.startswith("<") and value.endswith(">") else f"<{value}>"
    return f"<{uidl}@{_safe_atom(domain) or 'localhost'}>"


def _first_raw_text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        text = _value_text(value)
        if text:
            return text
    return ""


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "email", "address", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _value_text(item)
            if text:
                return text
    return ""


def _safe_header_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _safe_atom(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", value)


def _ensure_final_crlf(value: bytes) -> bytes:
    return value if value.endswith(_CRLF) or not value else value + _CRLF
