from __future__ import annotations

import html
import re
from datetime import timedelta

from app.gateway.business_models import MailMessage


_HTML_TAG = re.compile(r"<[^>]+>")
_NUMERIC_PATTERNS = (
    re.compile(r"(?i)(?:security|verification|one[- ]time)\s*(?:code)?\D{0,24}(\d{4,8})"),
    re.compile(r"(?:验证码|安全代码|一次性代码)[：:\s]*(\d{4,8})"),
    re.compile(r"(?:^|\D)(\d{6})(?:\D|$)"),
)
_ALPHANUMERIC_PATTERNS = (
    re.compile(r"(?i)(?:verification|security|one[- ]time)\s*(?:code)?\D{0,24}([A-Z0-9]{3,8}(?:-[A-Z0-9]{2,8})?)"),
    re.compile(r"(?:验证码|安全代码)[：:\s]*([A-Z0-9]{3,8}(?:-[A-Z0-9]{2,8})?)", re.I),
    re.compile(r"(?i)(?:^|\s)([A-Z0-9]{3,4}-[A-Z0-9]{3,4})(?:\s|$)"),
)


def extract_verification_code(
    messages: list[MailMessage],
    *,
    purpose: str,
    mailbox_created_at,
) -> str:
    lower_bound = mailbox_created_at - timedelta(seconds=5)
    for message in messages:
        if message.received_at is not None and message.received_at < lower_bound:
            continue
        direct = message.code.strip().upper()
        if direct and _valid_code(direct, purpose):
            return direct
        content = "\n".join(
            (message.subject, message.text, _HTML_TAG.sub(" ", html.unescape(message.html)))
        )
        patterns = _ALPHANUMERIC_PATTERNS if purpose.strip().lower() == "grok" else _NUMERIC_PATTERNS
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                return match.group(1).upper()
    return ""


def _valid_code(code: str, purpose: str) -> bool:
    if purpose.strip().lower() == "grok":
        return bool(re.fullmatch(r"[A-Z0-9]{3,8}(?:-[A-Z0-9]{2,8})?", code, re.I))
    return bool(re.fullmatch(r"\d{4,8}", code))
