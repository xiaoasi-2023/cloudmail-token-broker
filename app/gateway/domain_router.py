from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Callable

from app.gateway.addressing import normalize_domain
from app.gateway.business_errors import GatewayBusinessError
from app.gateway.business_models import CloudMailInstanceConfig, MailDomainConfig
from app.gateway.business_store import GatewayBusinessStore


class DomainRouter:
    def __init__(
        self,
        store: GatewayBusinessStore,
        *,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.store = store
        self.random_value = random_value

    def candidates(self, domain: str | None, domains: list[str] | None) -> list[tuple[MailDomainConfig, CloudMailInstanceConfig]]:
        if domain and domains:
            raise GatewayBusinessError(
                "DOMAIN_SELECTOR_CONFLICT",
                "domain 和 domains 不能同时传入",
                400,
            )
        configured = self.store.list_domains()
        by_name = {normalize_domain(item.domain): item for item in configured}
        requested_names: list[str] | None = None
        strict_single = False
        if domain:
            requested_names = [normalize_domain(domain)]
            strict_single = True
        elif domains:
            requested_names = list(dict.fromkeys(normalize_domain(item) for item in domains if item.strip()))
            if not requested_names:
                raise GatewayBusinessError("DOMAIN_NOT_ALLOWED", "域名候选范围不能为空", 400)

        if requested_names is not None:
            missing = [item for item in requested_names if item not in by_name]
            if missing:
                raise GatewayBusinessError("DOMAIN_NOT_ALLOWED", "指定域名不在可用域名池中", 400)
            selected = [by_name[item] for item in requested_names]
        else:
            selected = configured

        now = datetime.now(UTC)
        available: list[tuple[MailDomainConfig, CloudMailInstanceConfig]] = []
        for item in selected:
            instance = self.store.get_instance(item.instance_id)
            if instance is None or not self._available(item, instance, now):
                continue
            available.append((item, instance))

        if not available:
            code = "DOMAIN_UNAVAILABLE" if strict_single else "NO_AVAILABLE_DOMAIN"
            message = "指定邮箱域名当前不可用" if strict_single else "当前没有可用邮箱域名"
            raise GatewayBusinessError(code, message, 503)
        if strict_single:
            return available
        return self._weighted_order(available)

    @staticmethod
    def _available(domain: MailDomainConfig, instance: CloudMailInstanceConfig, now: datetime) -> bool:
        if not domain.enabled or not instance.enabled:
            return False
        if domain.status in {"disabled", "unhealthy"} or instance.health_status in {"disabled", "unhealthy"}:
            return False
        if domain.cooldown_until is not None and domain.cooldown_until > now:
            return False
        return True

    def _weighted_order(
        self,
        values: list[tuple[MailDomainConfig, CloudMailInstanceConfig]],
    ) -> list[tuple[MailDomainConfig, CloudMailInstanceConfig]]:
        remaining = list(values)
        ordered: list[tuple[MailDomainConfig, CloudMailInstanceConfig]] = []
        while remaining:
            total = sum(max(1, item[0].weight) for item in remaining)
            point = self.random_value() * total
            upto = 0
            selected_index = len(remaining) - 1
            for index, item in enumerate(remaining):
                upto += max(1, item[0].weight)
                if point < upto:
                    selected_index = index
                    break
            ordered.append(remaining.pop(selected_index))
        return ordered
