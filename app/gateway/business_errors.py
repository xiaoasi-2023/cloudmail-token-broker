from __future__ import annotations


class GatewayBusinessError(RuntimeError):
    """对外邮箱网关统一业务错误。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProviderRequestError(RuntimeError):
    """已脱敏的上游邮箱服务错误。"""

    def __init__(self, operation: str, *, retryable: bool = True) -> None:
        super().__init__(f"CloudMail {operation} 失败")
        self.operation = operation
        self.retryable = retryable
