from __future__ import annotations


class BrokerError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CloudMailTokenError(BrokerError):
    def __init__(self, message: str = "CloudMail Token 获取失败") -> None:
        super().__init__("CLOUDMAIL_TOKEN_FAILED", message, 502)
