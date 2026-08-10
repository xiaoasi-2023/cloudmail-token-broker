from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.gateway.database import GatewayDatabase


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    request_log_retention_days: int
    mailbox_retention_days: int
    request_log_cutoff: str
    mailbox_cutoff: str
    expired_idempotency: int
    expired_admin_sessions: int
    mailboxes_marked_expired: int
    request_logs_removed: int
    mailboxes_removed: int


def execute_cleanup(
    database: GatewayDatabase,
    *,
    request_log_retention_days: int,
    mailbox_retention_days: int,
    apply: bool,
    now: datetime | None = None,
) -> CleanupResult:
    current = now or datetime.now(UTC)
    request_log_cutoff = current - timedelta(days=max(1, request_log_retention_days))
    mailbox_cutoff = current - timedelta(days=max(1, mailbox_retention_days))

    with database.transaction() as connection:
        expired_idempotency = int(
            connection.execute(
                "SELECT COUNT(*) AS total FROM idempotency_records WHERE expires_at <= ?",
                (current.isoformat(),),
            ).fetchone()["total"]
        )
        expired_admin_sessions = int(
            connection.execute(
                "SELECT COUNT(*) AS total FROM admin_sessions WHERE expires_at <= ?",
                (current.isoformat(),),
            ).fetchone()["total"]
        )
        mailboxes_marked_expired = int(
            connection.execute(
                "SELECT COUNT(*) AS total FROM mailboxes WHERE status='active' AND expires_at <= ?",
                (current.isoformat(),),
            ).fetchone()["total"]
        )
        request_logs_removed = int(
            connection.execute(
                "SELECT COUNT(*) AS total FROM gateway_request_logs WHERE created_at < ?",
                (request_log_cutoff.isoformat(),),
            ).fetchone()["total"]
        )
        mailboxes_removed = int(
            connection.execute(
                """SELECT COUNT(*) AS total FROM mailboxes
                WHERE created_at < ? AND status IN ('released', 'expired', 'failed')""",
                (mailbox_cutoff.isoformat(),),
            ).fetchone()["total"]
        )

        if apply:
            mailboxes_marked_expired = connection.execute(
                "UPDATE mailboxes SET status='expired', updated_at=? WHERE status='active' AND expires_at <= ?",
                (current.isoformat(), current.isoformat()),
            ).rowcount
            connection.execute("DELETE FROM idempotency_records WHERE expires_at <= ?", (current.isoformat(),))
            connection.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (current.isoformat(),))
            request_logs_removed = connection.execute(
                "DELETE FROM gateway_request_logs WHERE created_at < ?",
                (request_log_cutoff.isoformat(),),
            ).rowcount
            mailboxes_removed = connection.execute(
                """DELETE FROM mailboxes
                WHERE created_at < ? AND status IN ('released', 'expired', 'failed')""",
                (mailbox_cutoff.isoformat(),),
            ).rowcount

    return CleanupResult(
        dry_run=not apply,
        request_log_retention_days=max(1, request_log_retention_days),
        mailbox_retention_days=max(1, mailbox_retention_days),
        request_log_cutoff=request_log_cutoff.isoformat(),
        mailbox_cutoff=mailbox_cutoff.isoformat(),
        expired_idempotency=expired_idempotency,
        expired_admin_sessions=expired_admin_sessions,
        mailboxes_marked_expired=mailboxes_marked_expired,
        request_logs_removed=request_logs_removed,
        mailboxes_removed=mailboxes_removed,
    )


def print_text(result: CleanupResult) -> None:
    print("-" * 76)
    print("Xiaoasi Mail Gateway 数据保留清理")
    print("-" * 76)
    print(f"执行模式: {'预览（不删除）' if result.dry_run else '实际执行'}")
    print(f"请求日志保留天数: {result.request_log_retention_days}")
    print(f"邮箱记录保留天数: {result.mailbox_retention_days}")
    print(f"过期幂等记录: {result.expired_idempotency}")
    print(f"过期管理会话: {result.expired_admin_sessions}")
    print(f"待标记过期邮箱: {result.mailboxes_marked_expired}")
    print(f"待清理请求日志: {result.request_logs_removed}")
    print(f"待清理历史邮箱记录: {result.mailboxes_removed}")
    print("说明: 不删除 CloudMail 上游邮箱账号，不删除仍处于 active 状态的未过期邮箱。")
    print("-" * 76)


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 Xiaoasi Mail Gateway 过期数据")
    parser.add_argument("--request-log-retention-days", type=int, default=30)
    parser.add_argument("--mailbox-retention-days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    database = GatewayDatabase(settings.database_url)
    database.initialize()
    result = execute_cleanup(
        database,
        request_log_retention_days=args.request_log_retention_days,
        mailbox_retention_days=args.mailbox_retention_days,
        apply=args.apply,
    )
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print_text(result)


if __name__ == "__main__":
    main()
