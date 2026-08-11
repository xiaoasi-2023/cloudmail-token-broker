from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.gateway.business_models import MailMessage
from app.gateway.pop3_server import Pop3Mailbox, Pop3Principal, Pop3Server


class FakeProvider:
    def __init__(self, messages: list[MailMessage]) -> None:
        self.messages = messages
        self.calls: list[tuple[str, int]] = []

    async def list_messages(self, mailbox: Pop3Mailbox, *, size: int) -> list[MailMessage]:
        self.calls.append((mailbox.address, size))
        return self.messages


def _messages() -> list[MailMessage]:
    return [
        MailMessage(
            subject="验证码",
            text="line one\n.line two",
            received_at=datetime(2026, 8, 11, 8, 30, tzinfo=UTC),
            raw={"emailId": "mail-1", "fromEmail": "sender@example.com"},
        ),
        MailMessage(subject="Second", text="second body", raw={"emailId": "mail-2"}),
    ]


async def _start_server(
    *,
    mailbox: Pop3Mailbox,
    provider: Any,
    max_connections: int = 100,
    max_auth_failures: int = 3,
    max_messages: int = 20,
    auth: Any = None,
) -> Pop3Server:
    async def authenticator(username: str, password: str) -> Pop3Principal | None:
        if auth is not None:
            return await auth(username, password)
        if username == "user@example.com" and password == "user-code":
            return Pop3Principal("user-1")
        if password == "admin-code":
            return Pop3Principal("admin-1", is_admin=True)
        return None

    async def resolver(address: str) -> Pop3Mailbox | None:
        return mailbox if address.casefold() == mailbox.address.casefold() else None

    server = Pop3Server(
        authenticator,
        resolver,
        provider,
        host="127.0.0.1",
        port=0,
        max_connections=max_connections,
        max_auth_failures=max_auth_failures,
        max_messages=max_messages,
    )
    await server.start()
    return server


def _address(server: Pop3Server) -> tuple[str, int]:
    socket = server.sockets[0]
    host, port = socket.getsockname()[:2]
    return host, port


async def _command(writer: asyncio.StreamWriter, reader: asyncio.StreamReader, command: str) -> str:
    writer.write(command.encode("ascii") + b"\r\n")
    await writer.drain()
    return (await asyncio.wait_for(reader.readline(), timeout=3)).decode("utf-8").rstrip("\r\n")


async def _multiline(reader: asyncio.StreamReader) -> list[str]:
    lines: list[str] = []
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        if line == b".\r\n":
            return lines
        lines.append(line.decode("utf-8").rstrip("\r\n"))


def test_pop3_state_machine_supports_read_only_commands_and_rfc822_retrieval() -> None:
    async def scenario() -> None:
        provider = FakeProvider(_messages())
        server = await _start_server(
            mailbox=Pop3Mailbox("user@example.com", "user-1", mailbox_id="mbx-1"),
            provider=provider,
        )
        try:
            reader, writer = await asyncio.open_connection(*_address(server))
            assert (await reader.readline()).startswith(b"+OK")
            assert await _command(writer, reader, "STAT") == "-ERR authentication required"

            assert await _command(writer, reader, "CAPA") == "+OK Capability list follows"
            capabilities = await _multiline(reader)
            assert "TOP" in capabilities
            assert "UIDL" in capabilities
            assert not any(line.startswith("STLS") for line in capabilities)

            assert await _command(writer, reader, "USER user@example.com") == "+OK user accepted"
            assert await _command(writer, reader, "PASS user-code") == "+OK maildrop has 2 messages"
            assert provider.calls == [("user@example.com", 20)]

            stat = await _command(writer, reader, "STAT")
            assert stat.startswith("+OK 2 ")
            assert await _command(writer, reader, "LIST") == "+OK 2 messages"
            listing = await _multiline(reader)
            assert listing[0].startswith("1 ")
            assert listing[1].startswith("2 ")

            assert await _command(writer, reader, "UIDL") == "+OK unique-id listing follows"
            assert await _multiline(reader) == ["1 mail-1", "2 mail-2"]

            assert await _command(writer, reader, "RETR 1") == "+OK " + listing[0].split()[1] + " octets"
            retrieved = await _multiline(reader)
            assert "From: sender@example.com" in retrieved
            assert "Message-ID: <mail-1@example.com>" in retrieved
            assert "..line two" in retrieved

            assert await _command(writer, reader, "TOP 1 1") == "+OK top of message follows"
            top = await _multiline(reader)
            assert any("Subject:" in line for line in top)
            assert any("line one" in line for line in top)
            assert not any("line two" in line for line in top)
            assert await _command(writer, reader, "NOOP") == "+OK"
            assert await _command(writer, reader, "RSET") == "+OK maildrop unchanged"
            assert await _command(writer, reader, "DELE 1") == "-ERR mailbox is read-only; DELE is not supported"
            assert await _command(writer, reader, "STLS") == "-ERR STLS is not available"
            assert await _command(writer, reader, "QUIT") == "+OK goodbye"
            writer.close()
            await writer.wait_closed()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_pop3_limits_messages_and_login_failures_without_leaking_details() -> None:
    async def scenario() -> None:
        provider = FakeProvider(_messages() * 3)
        server = await _start_server(
            mailbox=Pop3Mailbox("user@example.com", "user-1"),
            provider=provider,
            max_auth_failures=2,
            max_messages=1,
        )
        try:
            reader, writer = await asyncio.open_connection(*_address(server))
            await reader.readline()
            assert await _command(writer, reader, "USER user@example.com") == "+OK user accepted"
            assert await _command(writer, reader, "PASS wrong-code") == "-ERR authentication failed"
            assert await _command(writer, reader, "USER user@example.com") == "+OK user accepted"
            assert await _command(writer, reader, "PASS wrong-code") == "-ERR authentication failed"
            assert await reader.readline() == b""
            writer.close()
            await writer.wait_closed()
        finally:
            await server.close()

        server = await _start_server(
            mailbox=Pop3Mailbox("user@example.com", "user-1"),
            provider=provider,
            max_messages=1,
        )
        try:
            reader, writer = await asyncio.open_connection(*_address(server))
            await reader.readline()
            await _command(writer, reader, "USER user@example.com")
            assert await _command(writer, reader, "PASS user-code") == "+OK maildrop has 1 messages"
            assert (await _command(writer, reader, "STAT")).startswith("+OK 1 ")
            assert provider.calls[-1] == ("user@example.com", 1)
            await _command(writer, reader, "QUIT")
            writer.close()
            await writer.wait_closed()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_normal_user_cannot_access_other_owner_but_admin_can_access_expired_released_mailbox() -> None:
    async def scenario() -> None:
        mailbox = Pop3Mailbox(
            "other@example.com",
            "user-2",
            status="released",
            pop_enabled=False,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        provider = FakeProvider(_messages())
        server = await _start_server(mailbox=mailbox, provider=provider)
        try:
            reader, writer = await asyncio.open_connection(*_address(server))
            await reader.readline()
            await _command(writer, reader, "USER other@example.com")
            assert await _command(writer, reader, "PASS user-code") == "-ERR authentication failed"
            assert "user-2" not in provider.calls.__repr__()
            await _command(writer, reader, "QUIT")
            writer.close()
            await writer.wait_closed()

            reader, writer = await asyncio.open_connection(*_address(server))
            await reader.readline()
            await _command(writer, reader, "USER other@example.com")
            assert await _command(writer, reader, "PASS admin-code") == "+OK maildrop has 2 messages"
            assert (await _command(writer, reader, "STAT")).startswith("+OK 2 ")
            await _command(writer, reader, "QUIT")
            writer.close()
            await writer.wait_closed()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_connection_limit_returns_sanitized_error() -> None:
    async def scenario() -> None:
        mailbox = Pop3Mailbox("user@example.com", "user-1")
        server = await _start_server(mailbox=mailbox, provider=FakeProvider(_messages()), max_connections=1)
        try:
            reader_one, writer_one = await asyncio.open_connection(*_address(server))
            assert (await reader_one.readline()).startswith(b"+OK")
            reader_two, writer_two = await asyncio.open_connection(*_address(server))
            assert await reader_two.readline() == b"-ERR too many connections\r\n"
            assert await reader_two.readline() == b""
            writer_two.close()
            await writer_two.wait_closed()
            await _command(writer_one, reader_one, "QUIT")
            writer_one.close()
            await writer_one.wait_closed()
        finally:
            await server.close()

    asyncio.run(scenario())
