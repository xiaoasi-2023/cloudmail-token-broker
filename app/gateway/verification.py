from __future__ import annotations

import html
import re
from datetime import timedelta

from app.gateway.business_models import MailMessage


_STYLE_SCRIPT = re.compile(r"(?is)<(?:style|script)[^>]*>.*?</(?:style|script)>")
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
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
_IDENTITY_RULES: dict[str, re.Pattern[str]] = {
    "openai": re.compile(
        r"(?is)(?:temporary\s+(?:openai|chatgpt)\s+verification\s+code|"
        r"(?:openai|chatgpt).{0,80}(?:verification\s+code|临时验证码|登录代码)|"
        r"noreply@tm\.openai\.com)"
    ),
    "kiro": re.compile(
        r"(?is)(?:aws\s+builder\s+id|aws\s+构建者\s+id|aws\s+ビルダー\s+id|"
        r"no-reply@signin\.aws)"
    ),
    "cursor": re.compile(
        r"(?is)(?:register\s+cursor|注册\s*cursor|cursor\s+verification\s+code|"
        r"cursor.{0,80}one[- ]time\s+verification\s+code|"
        r"one[- ]time\s+verification\s+code.{0,80}cursor|"
        r"no-reply@cursor\.sh.{0,200}(?:verification\s+code|一次性验证码))"
    ),
    "grok": re.compile(
        r"(?is)(?:xai\s+confirmation\s+code|(?:grok|xai|x\.ai).{0,120}"
        r"(?:confirmation\s+code|validate\s+your\s+email)|"
        r"noreply@x\.ai.{0,200}(?:confirmation\s+code|validate\s+your\s+email))"
    ),
}
_PROJECT_FALLBACKS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(r"(?<!\d)(\d{6})(?!\d)"),
    "kiro": re.compile(r"(?<!\d)(\d{6})(?!\d)"),
    "cursor": re.compile(r"(?<!\d)(\d{6})(?!\d)"),
    "grok": re.compile(r"(?i)(?:^|[^A-Z0-9])([A-Z0-9]{3}-[A-Z0-9]{3})(?:[^A-Z0-9]|$)"),
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
        content = _message_content(message)
        identity_rule = _IDENTITY_RULES.get(normalized_purpose)
        identity_matched = identity_rule is None or bool(identity_rule.search(content))
        direct = message.code.strip().upper()
        # 与 EmailTool 一致：上游提供的候选 code 仍需通过邮件身份和格式校验。
        if direct and identity_matched and _valid_code(direct, normalized_purpose):
            return direct
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                return match.group(1).upper()
        # 与 EmailTool 的 ReceiveExtractCode -> mail.ExtractCode 兜底链路一致：
        # 邮件身份已确认后，项目专属上下文正则失败仍可按项目格式提取候选码。
        fallback = _PROJECT_FALLBACKS.get(normalized_purpose)
        if identity_matched and fallback is not None:
            match = fallback.search(content)
            if match:
                return match.group(1).upper()
    return ""


def _message_content(message: MailMessage) -> str:
    clean_html = html.unescape(_STYLE_SCRIPT.sub(" ", message.html))
    clean_html = _HTML_TAG.sub(" ", clean_html)
    sender = _raw_string(
        message,
        "from",
        "sendEmail",
        "sender",
        "fromEmail",
        "fromAddress",
        "send_email",
        "from_email",
    )
    # 邮件模板常用多层 table/div 排版，去标签后可能在提示语与验证码之间
    # 留下数百个换行和空格。先压缩空白，避免项目规则的安全距离被排版噪声耗尽。
    return _WHITESPACE.sub(
        " ",
        "\n".join((sender, message.subject, message.text, clean_html)),
    ).strip()


def _raw_string(message: MailMessage, *keys: str) -> str:
    for key in keys:
        value = message.raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _valid_code(code: str, purpose: str) -> bool:
    if purpose == "grok":
        return bool(re.fullmatch(r"[A-Z0-9]{3}-[A-Z0-9]{3}", code, re.I))
    if purpose in {"openai", "kiro", "cursor"}:
        return bool(re.fullmatch(r"\d{6}", code))
    return bool(re.fullmatch(r"\d{4,8}", code))
