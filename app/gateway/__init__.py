"""Xiaoasi Mail Gateway 后端基础模块。"""

from app.gateway.admin_api import AdminApiContext, create_admin_router
from app.gateway.admin_auth import AdminSessionService, hash_admin_password
from app.gateway.crypto import FernetSecretCipher, SecretCipher
from app.gateway.database import GatewayDatabase
from app.gateway.repository import GatewayRepository
from app.gateway.user_api import UserApiContext, create_user_router
from app.gateway.user_auth import UserSessionService
from app.gateway.user_repository import UserRepository

__all__ = [
    "AdminApiContext",
    "AdminSessionService",
    "FernetSecretCipher",
    "GatewayDatabase",
    "GatewayRepository",
    "SecretCipher",
    "UserApiContext",
    "UserRepository",
    "UserSessionService",
    "create_admin_router",
    "create_user_router",
    "hash_admin_password",
]
