from __future__ import annotations

from pydantic import BaseModel, Field


class RefreshRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)


class TokenData(BaseModel):
    token: str
    version: str
    expiresAt: str


class TokenResponse(BaseModel):
    code: int = 200
    data: TokenData
