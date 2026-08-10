from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.gateway.database import GatewayDatabase
from scripts.gateway_retention_cleanup import execute_cleanup


def test_cleanup_supports_dry_run_and_apply(tmp_path: Path) -> None:
    database = GatewayDatabase(tmp_path / "cleanup.db")
    database.initialize()
    now = datetime(2026, 8, 10, tzinfo=UTC)
    old = (now - timedelta(days=40)).isoformat()
    expired = (now - timedelta(hours=1)).isoformat()

    with database.transaction() as connection:
        instance_cursor = connection.execute(
            """INSERT INTO cloudmail_instances
            (name, base_url, admin_email, admin_password_encrypted, created_at, updated_at)
            VALUES ('cleanup-instance', 'https://mail.test', 'admin@test', 'encrypted', ?, ?)""",
            (old, old),
        )
        domain_cursor = connection.execute(
            """INSERT INTO mail_domains(instance_id, domain, created_at, updated_at)
            VALUES (?, 'cleanup.test', ?, ?)""",
            (instance_cursor.lastrowid, old, old),
        )
        connection.execute(
            """INSERT INTO mailboxes
            (id, address, domain_id, instance_id, status, created_at, expires_at, updated_at)
            VALUES ('mbx-old-active', 'old@cleanup.test', ?, ?, 'active', ?, ?, ?)""",
            (domain_cursor.lastrowid, instance_cursor.lastrowid, old, expired, old),
        )
        connection.execute(
            """INSERT INTO gateway_request_logs
            (request_id, endpoint, method, status_code, created_at)
            VALUES ('req-old', '/v1/mailboxes', 'POST', 200, ?)""",
            (old,),
        )
        connection.execute(
            """INSERT INTO admin_sessions
            (token_hash, username, created_at, expires_at, last_seen_at)
            VALUES ('token-old', 'admin', ?, ?, ?)""",
            (old, expired, old),
        )

    preview = execute_cleanup(
        database,
        request_log_retention_days=30,
        mailbox_retention_days=30,
        apply=False,
        now=now,
    )
    assert preview.dry_run is True
    assert preview.expired_admin_sessions == 1
    assert preview.request_logs_removed == 1
    assert preview.mailboxes_marked_expired == 1
    assert preview.mailboxes_removed == 0

    applied = execute_cleanup(
        database,
        request_log_retention_days=30,
        mailbox_retention_days=30,
        apply=True,
        now=now,
    )
    assert applied.dry_run is False
    assert applied.mailboxes_marked_expired == 1
    assert applied.mailboxes_removed == 1
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM gateway_request_logs").fetchone()[0] == 0
