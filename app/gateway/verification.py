from __future__ import annotations

import html
import re
from datetime import timedelta

from app.gateway.business_models import MailMessage


_STYLE_SCRIPT = re.compile(r"(?is)<(?:style|script)[^>]*>.*?</(?:style|script)>")
_HTML_TAG = re.compile(r"<[^>]+>")
_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "openai": (
        re.compile(r"(?is)(?:输入此临时验证码以继续|Enter this temporary verification code to continue)[^0-9]{0,80}([0-9]{6})"),
    ),
    "kiro": (
        re.compile(r"(?is)(?:验证码|認証コード|verification\s+code)[^0-9]{0,120}([0-9]{6})"),
    ),
    "cursor": (
        re.compile(r"(?is)(?:一次性验证码(?:是|为)?|one[- ]time verification code)[^0-9]{0,40}([0-9]{6})"),
    ),
    "grok": (
        re.compile(r"(?i)\b([A-Z0-9]{3}-[A-Z0-9]{3})\b"),
    ),
}
_GENERIC_RULES = (
    re.compile(r"(?i)(?:security|verification|one[- ]time)\s*(?:code)?\D{0,24}(\d{4,8})"),
    re.compile(r"(?:验证码|安全代码|一次性代码|認証コード)[：:\s]*(\d{4,8})", re.I),
)


def extract_verification_code(
    messages: list[MailMessage],
    *,
    purpose: str,
    mailbox_created_at,
) -> str:
    # 仅允许 15 秒的服务端/邮件提供方时钟偏差，避免后续任务误吃历史验证码。
    lower_bound = mailbox_created_at - timedelta(seconds=15)
    normalized_purpose = purpose.strip().lower()
    patterns = _RULES.get(normalized_purpose, _GENERIC_RULES)
    for message in messages:
        # CloudMail 部署版本的时间字段并不统一；有可靠时间时过滤旧信，
        # 无时间时仍允许识别，因为网关每次创建的是全新且唯一的邮箱地址。
        if message.received_at is not None and message.received_at < lower_bound:
            continue
        direct = message.code.strip().upper()
        if direct and _valid_code(direct, normalized_purpose):
            return direct
        content = _message_content(message)
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                return match.group(1).upper()
    return ""


def _message_content(message: MailMessage) -> str:
    clean_html = html.unescape(_STYLE_SCRIPT.sub(" ", message.html))
    clean_html = _HTML_TAG.sub(" ", clean_html)
    return "\n".join((message.subject, message.text, clean_html))


def _valid_code(code: str, purpose: str) -> bool:
    if purpose == "grok":
        return bool(re.fullmatch(r"[A-Z0-9]{3}-[A-Z0-9]{3}", code, re.I))
    if purpose in {"openai", "kiro", "cursor"}:
        return bool(re.fullmatch(r"\d{6}", code))
    return bool(re.fullmatch(r"\d{4,8}", code))
