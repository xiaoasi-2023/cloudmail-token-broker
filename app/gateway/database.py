from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2
logger = logging.getLogger("xiaoasi_mail_gateway.database")


class GatewayDatabase:
    """负责 SQLite 连接、事务和结构初始化。"""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if self.path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_schema (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cloudmail_instances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    base_url TEXT NOT NULL,
                    admin_email TEXT NOT NULL,
                    admin_password_encrypted TEXT NOT NULL,
                    proxy_url TEXT NOT NULL DEFAULT '',
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    health_status TEXT NOT NULL DEFAULT 'unknown',
                    last_checked_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mail_domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id INTEGER NOT NULL REFERENCES cloudmail_instances(id) ON DELETE CASCADE,
                    domain TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    weight INTEGER NOT NULL DEFAULT 100 CHECK(weight BETWEEN 1 AND 10000),
                    status TEXT NOT NULL DEFAULT 'unknown',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    cooldown_until TEXT,
                    last_used_at TEXT,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_total INTEGER NOT NULL DEFAULT 0,
                    remark TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mailboxes (
                    id TEXT PRIMARY KEY,
                    address TEXT NOT NULL UNIQUE,
                    domain_id INTEGER NOT NULL REFERENCES mail_domains(id),
                    instance_id INTEGER NOT NULL REFERENCES cloudmail_instances(id),
                    purpose TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    provider_reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency_records (
                    idempotency_key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    mailbox_id TEXT NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gateway_request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    method TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    mailbox_id TEXT,
                    instance_id INTEGER,
                    domain_id INTEGER,
                    status_code INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admin_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL DEFAULT '',
                    target_id TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                """
            )
            current = connection.execute("SELECT version FROM gateway_schema LIMIT 1").fetchone()
            if current is None:
                connection.execute("INSERT INTO gateway_schema(version) VALUES (0)")
                current_version = 0
            else:
                current_version = int(current["version"])

            if current_version > SCHEMA_VERSION:
                raise RuntimeError(f"不支持的 Gateway 数据库版本: {current['version']}")

            self._repair_additive_schema(connection)
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_domains_instance ON mail_domains(instance_id);
                CREATE INDEX IF NOT EXISTS idx_mailboxes_created ON mailboxes(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_request_logs_created ON gateway_request_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
                """
            )
            connection.execute("UPDATE gateway_schema SET version = ?", (SCHEMA_VERSION,))
            if current_version != SCHEMA_VERSION:
                logger.info("gateway_database_schema_upgraded from=%s to=%s", current_version, SCHEMA_VERSION)

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}

    def _add_missing_columns(
        self,
        connection: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = self._column_names(connection, table)
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
                logger.info("gateway_database_column_added table=%s column=%s", table, name)

    def _repair_additive_schema(self, connection: sqlite3.Connection) -> None:
        """补齐早期镜像创建的 SQLite 表字段，避免持久化旧库升级后管理接口报 500。"""

        self._add_missing_columns(
            connection,
            "cloudmail_instances",
            {
                "proxy_url": "TEXT NOT NULL DEFAULT ''",
                "verify_tls": "INTEGER NOT NULL DEFAULT 1",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
                "health_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "last_checked_at": "TEXT",
                "last_error": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            },
        )
        self._add_missing_columns(
            connection,
            "mail_domains",
            {
                "instance_id": "INTEGER REFERENCES cloudmail_instances(id) ON DELETE CASCADE",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
                "weight": "INTEGER NOT NULL DEFAULT 100",
                "status": "TEXT NOT NULL DEFAULT 'unknown'",
                "failure_count": "INTEGER NOT NULL DEFAULT 0",
                "cooldown_until": "TEXT",
                "last_used_at": "TEXT",
                "success_count": "INTEGER NOT NULL DEFAULT 0",
                "failure_total": "INTEGER NOT NULL DEFAULT 0",
                "remark": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            },
        )
        self._add_missing_columns(
            connection,
            "mailboxes",
            {
                "purpose": "TEXT NOT NULL DEFAULT ''",
                "source": "TEXT NOT NULL DEFAULT ''",
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
                "provider_reference": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "expires_at": "TEXT",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            },
        )
        self._add_missing_columns(
            connection,
            "gateway_request_logs",
            {
                "source": "TEXT NOT NULL DEFAULT ''",
                "mailbox_id": "TEXT",
                "instance_id": "INTEGER",
                "domain_id": "INTEGER",
                "duration_ms": "INTEGER NOT NULL DEFAULT 0",
                "error_code": "TEXT NOT NULL DEFAULT ''",
                "error_message": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            },
        )

        instance_ids = [row["id"] for row in connection.execute("SELECT id FROM cloudmail_instances ORDER BY id")]
        if len(instance_ids) == 1:
            connection.execute(
                "UPDATE mail_domains SET instance_id = ? WHERE instance_id IS NULL",
                (instance_ids[0],),
            )
