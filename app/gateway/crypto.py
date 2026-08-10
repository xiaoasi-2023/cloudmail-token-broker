from __future__ import annotations

import base64
import hashlib
from typing import Protocol


class SecretCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class FernetSecretCipher:
    """使用服务端主密钥加密 CloudMail 管理员密码。"""

    def __init__(self, master_secret: str) -> None:
        if len(master_secret.encode("utf-8")) < 32:
            raise ValueError("DATA_ENCRYPTION_KEY 至少需要 32 字节")
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover - 部署依赖缺失时给出明确提示
            raise RuntimeError("缺少 cryptography 依赖，无法启用敏感数据加密") from exc
        key = base64.urlsafe_b64encode(hashlib.sha256(master_secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
