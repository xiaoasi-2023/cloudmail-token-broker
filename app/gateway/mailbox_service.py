from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from app.gateway.addressing import generate_mailbox_address, generate_mailbox_password, normalize_domain
from app.gateway.business_errors import GatewayBusinessError, ProviderRequestError
from app.gateway.business_models import IdempotencyRecord, MailboxRecord
from app.gateway.business_store import GatewayBusinessStore
from app.gateway.cloudmail_provider import CloudMailProviderRegistry
from app.gateway.domain_router import DomainRouter
from app.gateway.gateway_schemas import (
    CreateMailboxRequest,
    MailboxData,
    MailboxStatusData,
    VerificationCodeData,
    VerificationCodeRequest,
)
from app.gateway.mailbox_token import MailboxTokenSigner
from app.gateway.user_repository import get_authenticated_user_id
from app.gateway.verification import extract_verification_code


class MailboxGatewayService:
    def __init__(
        self,
        store: GatewayBusinessStore,
        providers: CloudMailProviderRegistry,
        token_signer: MailboxTokenSigner,
        *,
        mailbox_ttl_seconds: int = 1800,
        max_create_attempts: int = 3,
        max_address_attempts: int = 5,
    ) -> None:
        self.store = store
        self.providers = providers
        self.token_signer = token_signer
        self.mailbox_ttl_seconds = mailbox_ttl_seconds
        self.max_create_attempts = max(1, max_create_attempts)
        self.max_address_attempts = max(1, max_address_attempts)
        self.router = DomainRouter(store)
        self._idempotency_locks: dict[str, tuple[asyncio.Lock, int]] = {}
        self._idempotency_locks_guard = asyncio.Lock()

    async def create_mailbox(
        self,
        request: CreateMailboxRequest,
        idempotency_key: str | None,
        client_name: str = "",
        user_id: int | None = None,
    ) -> MailboxData:
        owner_user_id = user_id if user_id is not None else get_authenticated_user_id()
        if owner_user_id is not None:
            owner_user_id = int(owner_user_id)
        if owner_user_id is not None and idempotency_key:
            internal_key = f"user:{owner_user_id}:{idempotency_key}"
        else:
            internal_key = f"{client_name}:{idempotency_key}" if client_name and idempotency_key else idempotency_key
        if not internal_key:
            return await self._create_mailbox(request, None, client_name, owner_user_id)
        async with self._idempotency_locks_guard:
            lock, users = self._idempotency_locks.get(
                internal_key,
                (asyncio.Lock(), 0),
            )
            self._idempotency_locks[internal_key] = (lock, users + 1)
        try:
            async with lock:
                return await self._create_mailbox(request, internal_key, client_name, owner_user_id)
        finally:
            async with self._idempotency_locks_guard:
                current = self._idempotency_locks.get(internal_key)
                if current is not None and current[0] is lock:
                    if current[1] <= 1:
                        self._idempotency_locks.pop(internal_key, None)
                    else:
                        self._idempotency_locks[internal_key] = (lock, current[1] - 1)

    async def _create_mailbox(
        self,
        request: CreateMailboxRequest,
        idempotency_key: str | None,
        client_name: str = "",
        owner_user_id: int | None = None,
    ) -> MailboxData:
        request_hash = _request_hash(request)
        if idempotency_key:
            existing = self.store.get_idempotency(idempotency_key)
            if existing:
                if existing.request_hash != request_hash:
                    raise GatewayBusinessError("IDEMPOTENCY_CONFLICT", "幂等键已用于不同的创建请求", 409)
                mailbox = self.store.get_mailbox(existing.mailbox_id)
                if mailbox:
                    return self._mailbox_data(mailbox)

        candidates = self.router.candidates(request.domain, request.domains)
        mailbox_id = f"mbx_{uuid.uuid4().hex}"
        credit_pending = False
        credit_reference = idempotency_key or mailbox_id
        if owner_user_id is not None:
            reserve_credit = getattr(self.store, "reserve_mailbox_credit", None)
            if reserve_credit is None:
                raise GatewayBusinessError("CREDIT_UNAVAILABLE", "积分服务当前不可用", 503)
            try:
                reserve_credit(owner_user_id, credit_reference)
            except ValueError as exc:
                if str(exc) == "INSUFFICIENT_CREDITS":
                    raise GatewayBusinessError("INSUFFICIENT_CREDITS", "积分余额不足", 402) from exc
                raise GatewayBusinessError("CREDIT_UNAVAILABLE", "积分服务当前不可用", 503) from exc
            credit_pending = True

        last_error: ProviderRequestError | None = None
        try:
            for domain, instance in candidates[: self.max_create_attempts]:
                address = ""
                candidate_error: ProviderRequestError | None = None
                client = await self.providers.client_for(instance)
                for _address_attempt in range(self.max_address_attempts):
                    address = generate_mailbox_address(
                        domain.domain,
                        pattern=request.address_pattern,
                        name=request.name,
                        prefix=request.prefix,
                    )
                    password = generate_mailbox_password()
                    try:
                        created = await client.create_mailbox(address, password)
                    except ProviderRequestError as exc:
                        self.store.mark_domain_failure(domain.id, "MAILBOX_CREATE_FAILED")
                        candidate_error = exc
                        last_error = exc
                        break
                    if created is not False:
                        break
                else:
                    # 用户名碰撞不代表域名异常，尝试下一个候选域名。
                    last_error = ProviderRequestError("创建邮箱", retryable=True)
                    if request.domain:
                        break
                    continue

                if candidate_error is not None:
                    if request.domain or not candidate_error.retryable:
                        break
                    continue

                now = datetime.now(UTC)
                mailbox = MailboxRecord(
                    id=mailbox_id,
                    address=address,
                    domain_id=domain.id,
                    instance_id=instance.id,
                    purpose=request.purpose.strip().lower(),
                    source=client_name,
                    provider_reference=address,
                    created_at=now,
                    expires_at=now + timedelta(seconds=self.mailbox_ttl_seconds),
                    owner_user_id=owner_user_id,
                )
                idempotency = None
                if idempotency_key:
                    idempotency = IdempotencyRecord(
                        key=idempotency_key,
                        request_hash=request_hash,
                        mailbox_id=mailbox.id,
                        expires_at=mailbox.expires_at,
                        user_id=owner_user_id,
                    )
                self.store.save_mailbox(mailbox, idempotency)
                if owner_user_id is not None:
                    self.store.confirm_mailbox_credit(owner_user_id, credit_reference)
                    credit_pending = False
                self.store.mark_domain_success(domain.id)
                return self._mailbox_data(mailbox)

            raise GatewayBusinessError(
                "MAILBOX_CREATE_FAILED",
                "邮箱创建失败，请稍后重试",
                502 if last_error is not None else 503,
            )
        except GatewayBusinessError:
            if credit_pending and owner_user_id is not None:
                self.store.refund_mailbox_credit(owner_user_id, credit_reference)
            raise
        except Exception as exc:
            if credit_pending and owner_user_id is not None:
                self.store.refund_mailbox_credit(owner_user_id, credit_reference)
            raise GatewayBusinessError("MAILBOX_CREATE_FAILED", "邮箱创建失败，请稍后重试", 502) from exc

    async def get_verification_code(
        self,
        mailbox_id: str,
        token: str,
        request: VerificationCodeRequest,
        client_name: str = "",
    ) -> VerificationCodeData:
        self.token_signer.verify(token, mailbox_id)
        mailbox = self.store.get_mailbox(mailbox_id)
        if mailbox is None:
            raise GatewayBusinessError("MAILBOX_NOT_FOUND", "邮箱记录不存在", 404)
        self._verify_client(mailbox, client_name)
        if mailbox.status != "active" or mailbox.expires_at <= datetime.now(UTC):
            raise GatewayBusinessError("MAILBOX_SESSION_EXPIRED", "邮箱会话已过期", 401)
        instance = self.store.get_instance(mailbox.instance_id)
        if instance is None or not instance.enabled:
            raise GatewayBusinessError("INSTANCE_UNAVAILABLE", "邮箱服务实例当前不可用", 503)

        deadline = time.monotonic() + request.wait_seconds
        purpose = request.purpose.strip().lower() or mailbox.purpose
        while True:
            try:
                client = await self.providers.client_for(instance)
                messages = await client.list_messages(mailbox.address)
            except ProviderRequestError as exc:
                raise GatewayBusinessError("MAILBOX_QUERY_FAILED", "查询邮箱失败，请稍后重试", 502) from exc
            code = extract_verification_code(
                messages,
                purpose=purpose,
                mailbox_created_at=mailbox.created_at,
            )
            if code:
                self.store.set_verification_status(mailbox.id, "received", code)
                return VerificationCodeData(status="received", verificationCode=code)
            if time.monotonic() >= deadline:
                if request.wait_seconds:
                    self.store.set_verification_status(mailbox.id, "timeout")
                return VerificationCodeData(status="pending", verificationCode="")
            await asyncio.sleep(min(request.poll_interval_seconds, max(0, deadline - time.monotonic())))

    def get_mailbox_status(self, mailbox_id: str, token: str, client_name: str = "") -> MailboxStatusData:
        self.token_signer.verify(token, mailbox_id)
        mailbox = self.store.get_mailbox(mailbox_id)
        if mailbox is None:
            raise GatewayBusinessError("MAILBOX_NOT_FOUND", "邮箱记录不存在", 404)
        self._verify_client(mailbox, client_name)
        status = mailbox.status
        if status == "active" and mailbox.expires_at <= datetime.now(UTC):
            status = "expired"
            self.store.set_mailbox_status(mailbox.id, status)
        return MailboxStatusData(
            mailboxId=mailbox.id,
            address=mailbox.address,
            domain=normalize_domain(mailbox.address.rsplit("@", 1)[-1]),
            status=status,
            verificationStatus=mailbox.verification_status,
            createdAt=mailbox.created_at.isoformat(),
            expiresAt=mailbox.expires_at.isoformat(),
        )

    def release_mailbox(self, mailbox_id: str, token: str, client_name: str = "") -> MailboxStatusData:
        self.token_signer.verify(token, mailbox_id)
        mailbox = self.store.get_mailbox(mailbox_id)
        if mailbox is None:
            raise GatewayBusinessError("MAILBOX_NOT_FOUND", "邮箱记录不存在", 404)
        self._verify_client(mailbox, client_name)
        self.store.set_mailbox_status(mailbox.id, "released")
        mailbox.status = "released"
        return MailboxStatusData(
            mailboxId=mailbox.id,
            address=mailbox.address,
            domain=normalize_domain(mailbox.address.rsplit("@", 1)[-1]),
            status="released",
            verificationStatus=mailbox.verification_status,
            createdAt=mailbox.created_at.isoformat(),
            expiresAt=mailbox.expires_at.isoformat(),
        )

    def _mailbox_data(self, mailbox: MailboxRecord) -> MailboxData:
        token = self.token_signer.issue(mailbox.id, int(mailbox.expires_at.timestamp()))
        return MailboxData(
            mailboxId=mailbox.id,
            address=mailbox.address,
            domain=normalize_domain(mailbox.address.rsplit("@", 1)[-1]),
            mailboxToken=token,
            createdAt=mailbox.created_at.isoformat(),
            expiresAt=mailbox.expires_at.isoformat(),
        )

    @staticmethod
    def _verify_client(mailbox: MailboxRecord, client_name: str) -> None:
        if client_name and mailbox.source != client_name:
            raise GatewayBusinessError("MAILBOX_ACCESS_DENIED", "当前调用密钥无权访问该邮箱", 403)
        authenticated_user_id = get_authenticated_user_id()
        if (
            mailbox.owner_user_id is not None
            and authenticated_user_id is not None
            and mailbox.owner_user_id != authenticated_user_id
        ):
            raise GatewayBusinessError("MAILBOX_ACCESS_DENIED", "当前用户无权访问该邮箱", 403)


def _request_hash(request: CreateMailboxRequest) -> str:
    payload = request.model_dump(mode="json")
    if payload.get("domain"):
        payload["domain"] = normalize_domain(payload["domain"])
    if payload.get("domains"):
        payload["domains"] = sorted(set(normalize_domain(item) for item in payload["domains"]))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
