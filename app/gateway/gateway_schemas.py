from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GatewaySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class CreateMailboxRequest(GatewaySchema):
    purpose: str = Field(default="openai", min_length=1, max_length=32)
    domain: str | None = Field(default=None, max_length=253)
    domains: list[str] | None = Field(default=None, max_length=100)
    prefix: str = Field(default="mail", max_length=32)
    source: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def validate_selector(self) -> "CreateMailboxRequest":
        if self.domain and self.domains:
            raise ValueError("domain 和 domains 不能同时传入")
        return self


class MailboxData(GatewaySchema):
    mailbox_id: str = Field(alias="mailboxId")
    address: str
    domain: str
    mailbox_token: str = Field(alias="mailboxToken")
    created_at: str = Field(alias="createdAt")
    expires_at: str = Field(alias="expiresAt")


class CreateMailboxResponse(GatewaySchema):
    code: int = 200
    data: MailboxData


class VerificationCodeRequest(GatewaySchema):
    purpose: str = Field(default="", max_length=32)
    wait_seconds: int = Field(default=0, alias="waitSeconds", ge=0, le=30)
    poll_interval_seconds: float = Field(default=2, alias="pollIntervalSeconds", ge=0.2, le=10)


class VerificationCodeData(GatewaySchema):
    status: str
    verification_code: str = Field(default="", alias="verificationCode")


class VerificationCodeResponse(GatewaySchema):
    code: int = 200
    data: VerificationCodeData


class MailboxStatusData(GatewaySchema):
    mailbox_id: str = Field(alias="mailboxId")
    address: str
    domain: str
    status: str
    verification_status: str = Field(alias="verificationStatus")
    created_at: str = Field(alias="createdAt")
    expires_at: str = Field(alias="expiresAt")


class MailboxStatusResponse(GatewaySchema):
    code: int = 200
    data: MailboxStatusData
