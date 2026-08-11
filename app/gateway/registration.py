from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import escape

from app.gateway.database import GatewayDatabase
from app.gateway.user_repository import UserRepository


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserRegistrationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RegistrationEmailSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_tls: bool = True


class RegistrationEmailSender:
    def __init__(self, settings: RegistrationEmailSettings) -> None:
        self.settings = settings

    @staticmethod
    def _html(code: str, ttl_minutes: int) -> str:
        safe_code = escape(code)
        return f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;background:#f4f3ed;color:#202724;font-family:Arial,'Microsoft YaHei',sans-serif;">
    <div style="padding:32px 16px;">
      <div style="max-width:560px;margin:0 auto;border:1px solid #d7d8cf;background:#fffdf8;">
        <div style="padding:20px 24px;background:#18201d;color:#f3f2eb;font-size:13px;letter-spacing:.14em;">XIAOASI MAIL</div>
        <div style="padding:30px 24px;">
          <h1 style="margin:0;font-size:24px;">用户注册验证码</h1>
          <p style="margin:14px 0;color:#68716d;line-height:1.7;">你正在注册 Xiaoasi Mail 用户中心，请输入下面的验证码完成邮箱验证。</p>
          <div style="margin:26px 0;padding:18px;border:1px solid #b6c8be;background:#eef4f0;text-align:center;font-family:Consolas,monospace;font-size:36px;font-weight:700;letter-spacing:.22em;color:#315746;">{safe_code}</div>
          <p style="margin:0;color:#7b827e;font-size:12px;line-height:1.7;">验证码 {ttl_minutes} 分钟内有效。若不是你本人操作，请忽略此邮件。</p>
        </div>
      </div>
    </div>
  </body>
</html>"""

    def send_code(self, email: str, code: str, ttl_seconds: int) -> None:
        settings = self.settings
        message = EmailMessage()
        message["Subject"] = "Xiaoasi Mail 用户注册验证码"
        message["From"] = settings.sender or settings.username
        message["To"] = email
        ttl_minutes = max(1, (ttl_seconds + 59) // 60)
        message.set_content(f"你的注册验证码是：{code}，{ttl_minutes} 分钟内有效。")
        message.add_alternative(self._html(code, ttl_minutes), subtype="html")

        try:
            if settings.use_tls:
                with smtplib.SMTP_SSL(settings.host, settings.port, timeout=15) as client:
                    client.login(settings.username, settings.password)
                    client.send_message(message)
            else:
                with smtplib.SMTP(settings.host, settings.port, timeout=15) as client:
                    client.starttls()
                    client.login(settings.username, settings.password)
                    client.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise UserRegistrationError("SMTP_AUTH_FAILED", "邮件服务认证失败，请联系管理员", 502) from exc
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            raise UserRegistrationError("EMAIL_SEND_FAILED", "验证码邮件发送失败，请稍后重试", 502) from exc


class UserRegistrationService:
    def __init__(
        self,
        database: GatewayDatabase,
        users: UserRepository,
        sender: RegistrationEmailSender,
        *,
        code_secret: str,
        ttl_seconds: int = 600,
        cooldown_seconds: int = 60,
        max_attempts: int = 5,
    ) -> None:
        self.database = database
        self.users = users
        self.sender = sender
        self.code_secret = code_secret.encode("utf-8")
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.cooldown_seconds = max(10, int(cooldown_seconds))
        self.max_attempts = max(1, int(max_attempts))

    @staticmethod
    def normalize_email(value: str) -> str:
        email = str(value or "").strip().lower()
        if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
            raise UserRegistrationError("EMAIL_INVALID", "请输入有效的邮箱地址")
        return email

    def _hash_code(self, email: str, code: str) -> str:
        payload = f"register:{email}:{code}".encode("utf-8")
        return hmac.new(self.code_secret, payload, hashlib.sha256).hexdigest()

    def send_code(self, email: str) -> dict[str, int | bool]:
        normalized_email = self.normalize_email(email)
        if self.users.get_user_by_email(normalized_email) is not None:
            raise UserRegistrationError("USER_CONFLICT", "该邮箱已注册", 409)

        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM user_registration_codes WHERE expires_at<?",
                ((now - timedelta(days=1)).isoformat(),),
            )
            latest = connection.execute(
                """SELECT created_at FROM user_registration_codes
                WHERE email=? ORDER BY created_at DESC LIMIT 1""",
                (normalized_email,),
            ).fetchone()
            if latest is not None:
                latest_at = datetime.fromisoformat(str(latest["created_at"]))
                retry_at = latest_at + timedelta(seconds=self.cooldown_seconds)
                if retry_at > now:
                    retry_after = max(1, int((retry_at - now).total_seconds()))
                    raise UserRegistrationError(
                        "REGISTER_CODE_TOO_FREQUENT",
                        f"验证码发送过于频繁，请 {retry_after} 秒后再试",
                        429,
                    )

            connection.execute(
                "UPDATE user_registration_codes SET consumed=1 WHERE email=? AND consumed=0",
                (normalized_email,),
            )
            code = f"{secrets.randbelow(1_000_000):06d}"
            code_id = secrets.token_hex(16)
            connection.execute(
                """INSERT INTO user_registration_codes
                (id,email,code_hash,consumed,attempts,created_at,expires_at)
                VALUES (?,?,?,0,0,?,?)""",
                (
                    code_id,
                    normalized_email,
                    self._hash_code(normalized_email, code),
                    now.isoformat(),
                    (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
                ),
            )

        try:
            self.sender.send_code(normalized_email, code, self.ttl_seconds)
        except UserRegistrationError:
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM user_registration_codes WHERE id=?", (code_id,))
            raise

        return {
            "ok": True,
            "ttl_seconds": self.ttl_seconds,
            "cooldown_seconds": self.cooldown_seconds,
        }

    def register(self, *, username: str, email: str, password: str, code: str) -> dict:
        normalized_email = self.normalize_email(email)
        normalized_username = str(username or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,100}", normalized_username):
            raise UserRegistrationError(
                "USERNAME_INVALID",
                "用户账号需为 3-100 位，只能包含字母、数字、点、下划线和短横线",
            )
        normalized_code = str(code or "").strip()
        if not re.fullmatch(r"\d{6}", normalized_code):
            raise UserRegistrationError("REGISTER_CODE_INVALID", "验证码错误或已过期")

        user = self.users.create_user_from_registration(
            username=normalized_username,
            email=normalized_email,
            password=password,
            code_hash=self._hash_code(normalized_email, normalized_code),
            max_attempts=self.max_attempts,
        )
        if user is None:
            raise UserRegistrationError(
                getattr(self.users, "error_code", "REGISTER_CODE_INVALID"),
                getattr(self.users, "error", "验证码错误或已过期"),
            )
        return user


__all__ = [
    "RegistrationEmailSender",
    "RegistrationEmailSettings",
    "UserRegistrationError",
    "UserRegistrationService",
]
