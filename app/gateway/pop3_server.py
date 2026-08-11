from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeAlias

from app.gateway.business_models import MailMessage
from app.gateway.pop3_message import Pop3RenderedMessage, dot_stuff, render_mail_message


@dataclass(frozen=True, slots=True)
class Pop3Principal:
    """The result of POP3 USER/PASS authentication."""

    user_id: str
    is_admin: bool = False


@dataclass(frozen=True, slots=True)
class Pop3Mailbox:
    """A provider-independent mailbox view used by the POP3 adapter."""

    address: str
    owner_user_id: str | int | None
    provider_mailbox: Any = None
    mailbox_id: str = ""
    status: str = "active"
    pop_enabled: bool = True
    expires_at: datetime | None = None


class Pop3MessageProvider(Protocol):
    async def list_messages(self, mailbox: Pop3Mailbox, *, size: int) -> Sequence[MailMessage]: ...


Pop3Authenticator: TypeAlias = Callable[
    [str, str],
    Pop3Principal | None | Awaitable[Pop3Principal | None],
]
Pop3MailboxResolver: TypeAlias = Callable[
    [str],
    Pop3Mailbox | None | Awaitable[Pop3Mailbox | None],
]
Pop3MessageLoader: TypeAlias = Callable[
    [Pop3Mailbox, int],
    Sequence[MailMessage] | Awaitable[Sequence[MailMessage]],
]


class Pop3Server:
    """A small read-only POP3 server intended to run beside the HTTP app."""

    def __init__(
        self,
        authenticator: Pop3Authenticator,
        mailbox_resolver: Pop3MailboxResolver,
        message_provider: Pop3MessageProvider | Pop3MessageLoader,
        *,
        host: str = "127.0.0.1",
        port: int = 8110,
        max_connections: int = 100,
        max_auth_failures: int = 3,
        max_messages: int = 20,
        max_line_length: int = 2048,
    ) -> None:
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        if max_auth_failures < 1:
            raise ValueError("max_auth_failures must be positive")
        if max_messages < 1:
            raise ValueError("max_messages must be positive")
        if max_line_length < 128:
            raise ValueError("max_line_length is too small")

        self.authenticator = authenticator
        self.mailbox_resolver = mailbox_resolver
        self.message_provider = message_provider
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.max_auth_failures = max_auth_failures
        self.max_messages = max_messages
        self.max_line_length = max_line_length
        self._server: asyncio.AbstractServer | None = None
        self._active_connections = 0
        self._connection_lock = asyncio.Lock()

    @property
    def server(self) -> asyncio.AbstractServer | None:
        return self._server

    @property
    def sockets(self) -> tuple[Any, ...]:
        if self._server is None:
            return ()
        return tuple(self._server.sockets or ())

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            limit=self.max_line_length + 2,
        )

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        await self._server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not await self._try_reserve_connection():
            await self._write_line(writer, "-ERR too many connections")
            await self._close_writer(writer)
            return

        try:
            session = _Pop3Session(self, reader, writer)
            await session.run()
        finally:
            await self._release_connection()

    async def _try_reserve_connection(self) -> bool:
        async with self._connection_lock:
            if self._active_connections >= self.max_connections:
                return False
            self._active_connections += 1
            return True

    async def _release_connection(self) -> None:
        async with self._connection_lock:
            self._active_connections = max(0, self._active_connections - 1)

    @staticmethod
    async def _write_line(writer: asyncio.StreamWriter, value: str) -> None:
        writer.write(value.encode("ascii") + b"\r\n")
        await writer.drain()

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, asyncio.CancelledError):
            pass


class _Pop3Session:
    def __init__(self, server: Pop3Server, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.server = server
        self.reader = reader
        self.writer = writer
        self.username = ""
        self.principal: Pop3Principal | None = None
        self.mailbox: Pop3Mailbox | None = None
        self.messages: list[Pop3RenderedMessage] = []
        self.auth_failures = 0
        self.closed = False

    async def run(self) -> None:
        try:
            await self._send("+OK CloudMail POP3 ready")
            while not self.closed:
                try:
                    line = await self.reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    await self._send("-ERR command line too long")
                    break
                if not line:
                    break
                if len(line) > self.server.max_line_length + 2:
                    await self._send("-ERR command line too long")
                    break
                command, argument = self._parse_command(line)
                if not command:
                    await self._send("-ERR invalid command")
                    continue
                await self._dispatch(command, argument)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            await self.server._close_writer(self.writer)

    @staticmethod
    def _parse_command(line: bytes) -> tuple[str, str]:
        text = line.decode("utf-8", errors="replace").strip("\r\n")
        if not text:
            return "", ""
        command, separator, argument = text.partition(" ")
        return command.upper(), argument.strip() if separator else ""

    async def _dispatch(self, command: str, argument: str) -> None:
        if command == "CAPA":
            await self._capa(argument)
        elif command == "USER":
            await self._user(argument)
        elif command == "PASS":
            await self._pass(argument)
        elif command == "STAT":
            await self._stat(argument)
        elif command == "LIST":
            await self._list(argument)
        elif command == "UIDL":
            await self._uidl(argument)
        elif command == "RETR":
            await self._retr(argument)
        elif command == "TOP":
            await self._top(argument)
        elif command == "NOOP":
            await self._noop(argument)
        elif command == "RSET":
            await self._rset(argument)
        elif command == "QUIT":
            await self._quit(argument)
        elif command == "STLS":
            await self._send("-ERR STLS is not available")
        elif command == "DELE":
            await self._send("-ERR mailbox is read-only; DELE is not supported")
        else:
            await self._send("-ERR unknown command")

    async def _capa(self, argument: str) -> None:
        if argument:
            await self._send("-ERR invalid arguments")
            return
        await self._send_multiline(
            "+OK Capability list follows",
            ("TOP", "UIDL", "RESP-CODES", "IMPLEMENTATION cloudmail-pop3-readonly"),
        )

    async def _user(self, argument: str) -> None:
        if self.principal is not None:
            await self._send("-ERR already authenticated")
            return
        if not argument or len(argument) > 320:
            await self._send("-ERR invalid arguments")
            return
        self.username = argument
        await self._send("+OK user accepted")

    async def _pass(self, argument: str) -> None:
        if self.principal is not None:
            await self._send("-ERR already authenticated")
            return
        if not self.username:
            await self._send("-ERR USER required")
            return
        if not argument or len(argument) > 512:
            await self._authentication_failed()
            return

        try:
            principal = await _maybe_await(self.server.authenticator(self.username, argument))
        except Exception:
            principal = None
        if principal is None:
            await self._authentication_failed()
            return

        try:
            mailbox = await _maybe_await(self.server.mailbox_resolver(self.username))
        except Exception:
            await self._send("-ERR mailbox temporarily unavailable")
            return
        if mailbox is None or not self._is_allowed(mailbox, principal):
            await self._authentication_failed()
            return

        try:
            messages = await self._load_messages(mailbox)
            rendered = [render_mail_message(message, mailbox.address) for message in messages]
        except Exception:
            await self._send("-ERR mailbox temporarily unavailable")
            return

        self.principal = principal
        self.mailbox = mailbox
        self.messages = rendered
        self.auth_failures = 0
        await self._send(f"+OK maildrop has {len(rendered)} messages")

    async def _stat(self, argument: str) -> None:
        if not await self._require_transaction(argument):
            return
        await self._send(f"+OK {len(self.messages)} {sum(message.size for message in self.messages)}")

    async def _list(self, argument: str) -> None:
        if not await self._require_transaction():
            return
        if not argument:
            lines = tuple(f"{index} {message.size}" for index, message in enumerate(self.messages, 1))
            await self._send_multiline(f"+OK {len(self.messages)} messages", lines)
            return
        message = self._message_for_argument(argument)
        if message is None:
            await self._send("-ERR no such message")
            return
        index = self.messages.index(message) + 1
        await self._send(f"+OK {index} {message.size}")

    async def _uidl(self, argument: str) -> None:
        if not await self._require_transaction():
            return
        if not argument:
            lines = tuple(f"{index} {message.uidl}" for index, message in enumerate(self.messages, 1))
            await self._send_multiline("+OK unique-id listing follows", lines)
            return
        message = self._message_for_argument(argument)
        if message is None:
            await self._send("-ERR no such message")
            return
        index = self.messages.index(message) + 1
        await self._send(f"+OK {index} {message.uidl}")

    async def _retr(self, argument: str) -> None:
        if not await self._require_transaction():
            return
        message = self._message_for_argument(argument)
        if message is None:
            await self._send("-ERR no such message")
            return
        await self._send(f"+OK {message.size} octets")
        await self._send_multiline_body(message.data)

    async def _top(self, argument: str) -> None:
        if not await self._require_transaction():
            return
        parts = argument.split()
        if len(parts) != 2:
            await self._send("-ERR invalid arguments")
            return
        try:
            index = int(parts[0])
            body_lines = int(parts[1])
        except ValueError:
            await self._send("-ERR invalid arguments")
            return
        if body_lines < 0 or index < 1 or index > len(self.messages):
            await self._send("-ERR no such message")
            return
        await self._send("+OK top of message follows")
        await self._send_multiline_body(self.messages[index - 1].top(body_lines))

    async def _noop(self, argument: str) -> None:
        if argument:
            await self._send("-ERR invalid arguments")
            return
        await self._send("+OK")

    async def _rset(self, argument: str) -> None:
        if not await self._require_transaction(argument):
            return
        await self._send("+OK maildrop unchanged")

    async def _quit(self, argument: str) -> None:
        if argument:
            await self._send("-ERR invalid arguments")
            return
        await self._send("+OK goodbye")
        self.closed = True

    async def _require_transaction(self, argument: str = "") -> bool:
        if argument:
            await self._send("-ERR invalid arguments")
            return False
        if self.principal is None or self.mailbox is None:
            await self._send("-ERR authentication required")
            return False
        return True

    def _message_for_argument(self, argument: str) -> Pop3RenderedMessage | None:
        try:
            index = int(argument)
        except ValueError:
            return None
        if index < 1 or index > len(self.messages):
            return None
        return self.messages[index - 1]

    def _is_allowed(self, mailbox: Pop3Mailbox, principal: Pop3Principal) -> bool:
        if principal.is_admin:
            return True
        if mailbox.owner_user_id is None or str(mailbox.owner_user_id) != str(principal.user_id):
            return False
        if not mailbox.pop_enabled or mailbox.status != "active":
            return False
        if mailbox.expires_at is not None:
            expires_at = mailbox.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= datetime.now(UTC):
                return False
        return True

    async def _load_messages(self, mailbox: Pop3Mailbox) -> list[MailMessage]:
        provider = self.server.message_provider
        if hasattr(provider, "list_messages"):
            value = provider.list_messages(mailbox, size=self.server.max_messages)  # type: ignore[attr-defined]
        else:
            value = provider(mailbox, self.server.max_messages)  # type: ignore[operator]
        messages = await _maybe_await(value)
        return list(messages)[: self.server.max_messages]

    async def _authentication_failed(self) -> None:
        self.username = ""
        self.principal = None
        self.mailbox = None
        self.messages = []
        self.auth_failures += 1
        await self._send("-ERR authentication failed")
        if self.auth_failures >= self.server.max_auth_failures:
            self.closed = True

    async def _send(self, line: str) -> None:
        await self.server._write_line(self.writer, line)

    async def _send_multiline(self, first_line: str, lines: Sequence[str]) -> None:
        await self._send(first_line)
        for line in lines:
            await self._send(line)
        await self._send(".")

    async def _send_multiline_body(self, body: bytes) -> None:
        self.writer.write(dot_stuff(body) + b".\r\n")
        await self.writer.drain()


async def _maybe_await(value: Any) -> Any:
    if isinstance(value, Awaitable):
        return await value
    return value
