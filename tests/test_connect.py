"""
Connectivity tests.
"""
import asyncio
import email
import pathlib
import socket
from typing import Any, Callable, Coroutine, List, Optional, Tuple, Type, Union

import pytest
from aiosmtpd.smtp import SMTP as SMTPD

from aiosmtplib import (
    SMTP,
    SMTPConnectError,
    SMTPResponseException,
    SMTPServerDisconnected,
    SMTPStatus,
)


pytestmark = pytest.mark.asyncio()


@pytest.fixture(scope="session")
def close_during_read_response_handler() -> Callable[
    [SMTPD], Coroutine[Any, Any, None]
]:
    async def close_during_read_response(
        smtpd: SMTPD, *args: Any, **kwargs: Any
    ) -> None:
        # Read one line of data, then cut the connection.
        await smtpd.push(f"{SMTPStatus.start_input} End data with <CR><LF>.<CR><LF>")

        await smtpd._reader.readline()
        smtpd.transport.close()

    return close_during_read_response


async def test_plain_smtp_connect(
    smtp_client: SMTP, smtpd_server: asyncio.AbstractServer
) -> None:
    """
    Use an explicit connect/quit here, as other tests use the context manager.
    """
    await smtp_client.connect()
    assert smtp_client.is_connected

    await smtp_client.quit()
    assert not smtp_client.is_connected


async def test_quit_then_connect_ok(
    smtp_client: SMTP, smtpd_server: asyncio.AbstractServer
) -> None:
    async with smtp_client:
        response = await smtp_client.quit()
        assert response.code == SMTPStatus.closing

        # Next command should fail
        with pytest.raises(SMTPServerDisconnected):
            response = await smtp_client.noop()

        await smtp_client.connect()

        # after reconnect, it should work again
        response = await smtp_client.noop()
        assert response.code == SMTPStatus.completed


async def test_bad_connect_response_raises_error(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        f"{SMTPStatus.domain_unavailable} retry in 5 minutes",
        None,
        False,
        True,
    )
    monkeypatch.setattr(smtpd_class, "_handle_client", response_handler)

    with pytest.raises(SMTPConnectError):
        await smtp_client.connect()

    assert smtp_client.transport is None
    assert smtp_client.protocol is None


async def test_eof_on_connect_raises_connect_error(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        None,
        None,
        True,
        False,
    )
    monkeypatch.setattr(smtpd_class, "_handle_client", response_handler)

    with pytest.raises(SMTPConnectError):
        await smtp_client.connect()

    assert smtp_client.transport is None
    assert smtp_client.protocol is None


async def test_close_on_connect_raises_connect_error(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        None,
        None,
        False,
        True,
    )
    monkeypatch.setattr(smtpd_class, "_handle_client", response_handler)

    with pytest.raises(SMTPConnectError):
        await smtp_client.connect()

    assert smtp_client.transport is None
    assert smtp_client.protocol is None


async def test_421_closes_connection(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        f"{SMTPStatus.domain_unavailable} Please come back in 15 seconds.",
        None,
        False,
        False,
    )

    monkeypatch.setattr(smtpd_class, "smtp_NOOP", response_handler)

    await smtp_client.connect()

    with pytest.raises(SMTPResponseException):
        await smtp_client.noop()

    assert not smtp_client.is_connected


async def test_connect_error_with_no_server(
    hostname: str, unused_tcp_port: int
) -> None:
    client = SMTP(hostname=hostname, port=unused_tcp_port)

    with pytest.raises(SMTPConnectError):
        # SMTPConnectTimeoutError vs SMTPConnectError here depends on
        # processing time.
        await client.connect(timeout=1.0)


async def test_disconnected_server_raises_on_client_read(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        None,
        None,
        False,
        True,
    )
    monkeypatch.setattr(smtpd_class, "smtp_NOOP", response_handler)

    await smtp_client.connect()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.execute_command(b"NOOP")

    assert smtp_client.protocol is None
    assert smtp_client.transport is None


async def test_disconnected_server_raises_on_client_write(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        None,
        None,
        True,
        True,
    )
    monkeypatch.setattr(smtpd_class, "smtp_NOOP", response_handler)

    await smtp_client.connect()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.execute_command(b"NOOP")

    assert smtp_client.protocol is None
    assert smtp_client.transport is None


async def test_disconnected_server_raises_on_data_read(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The `data` command is a special case - it accesses protocol directly,
    rather than using `execute_command`.
    """
    response_handler = smtpd_response_handler_factory(
        None,
        None,
        False,
        True,
    )
    monkeypatch.setattr(smtpd_class, "smtp_DATA", response_handler)

    await smtp_client.connect()
    await smtp_client.ehlo()
    await smtp_client.mail("sender@example.com")
    await smtp_client.rcpt("recipient@example.com")

    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.data("A MESSAGE")

    assert smtp_client.protocol is None
    assert smtp_client.transport is None


async def test_disconnected_server_raises_on_data_write(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    close_during_read_response_handler: Callable[[SMTPD], Coroutine[Any, Any, None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The `data` command is a special case - it accesses protocol directly,
    rather than using `execute_command`.
    """
    monkeypatch.setattr(smtpd_class, "smtp_DATA", close_during_read_response_handler)

    await smtp_client.connect()
    await smtp_client.ehlo()
    await smtp_client.mail("sender@example.com")
    await smtp_client.rcpt("recipient@example.com")
    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.data("A MESSAGE\nLINE2")

    assert smtp_client.protocol is None
    assert smtp_client.transport is None


async def test_disconnected_server_raises_on_starttls(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The `starttls` command is a special case - it accesses protocol directly,
    rather than using `execute_command`.
    """
    response_handler = smtpd_response_handler_factory(None, None, False, True)
    monkeypatch.setattr(smtpd_class, "smtp_STARTTLS", response_handler)

    await smtp_client.connect()
    await smtp_client.ehlo()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.starttls(validate_certs=False, timeout=1.0)

    assert smtp_client.protocol is None
    assert smtp_client.transport is None


async def test_context_manager(
    smtp_client: SMTP, smtpd_server: asyncio.AbstractServer
) -> None:
    async with smtp_client:
        assert smtp_client.is_connected

        response = await smtp_client.noop()
        assert response.code == SMTPStatus.completed

    assert not smtp_client.is_connected


async def test_context_manager_disconnect_handling(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Exceptions can be raised, but the context manager should handle
    disconnection.
    """
    response_handler = smtpd_response_handler_factory(None, None, False, True)
    monkeypatch.setattr(smtpd_class, "smtp_NOOP", response_handler)

    async with smtp_client:
        assert smtp_client.is_connected

        try:
            await smtp_client.noop()
        except SMTPServerDisconnected:
            pass

    assert not smtp_client.is_connected


async def test_context_manager_exception_quits(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    received_commands: List[Tuple[str, Tuple[Any, ...]]],
) -> None:
    with pytest.raises(ZeroDivisionError):
        async with smtp_client:
            1 / 0

    assert received_commands[-1][0] == "QUIT"


async def test_context_manager_connect_exception_closes(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    received_commands: List[Tuple[str, Tuple[Any, ...]]],
) -> None:
    with pytest.raises(ConnectionError):
        async with smtp_client:
            raise ConnectionError("Failed!")

    assert len(received_commands) == 0


async def test_context_manager_with_manual_connection(
    smtp_client: SMTP, smtpd_server: asyncio.AbstractServer
) -> None:
    await smtp_client.connect()

    assert smtp_client.is_connected

    async with smtp_client:
        assert smtp_client.is_connected

        await smtp_client.quit()

        assert not smtp_client.is_connected

    assert not smtp_client.is_connected


async def test_context_manager_double_entry(
    smtp_client: SMTP, smtpd_server: asyncio.AbstractServer
) -> None:
    async with smtp_client:
        async with smtp_client:
            assert smtp_client.is_connected
            response = await smtp_client.noop()
            assert response.code == SMTPStatus.completed

        # The first exit should disconnect us
        assert not smtp_client.is_connected
    assert not smtp_client.is_connected


async def test_connect_error_second_attempt(
    hostname: str, unused_tcp_port: int
) -> None:
    client = SMTP(hostname=hostname, port=unused_tcp_port, timeout=1.0)

    with pytest.raises(SMTPConnectError):
        await client.connect()

    with pytest.raises(SMTPConnectError):
        await client.connect()


async def test_server_unexpected_disconnect(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    smtpd_class: Type[SMTPD],
    smtpd_response_handler_factory: Callable[
        [Optional[str], Optional[str], bool, bool],
        Coroutine[Any, Any, None],
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_handler = smtpd_response_handler_factory(
        f"{SMTPStatus.completed} OK",
        f"{SMTPStatus.closing} Bye now!",
        False,
        True,
    )

    monkeypatch.setattr(smtpd_class, "smtp_EHLO", response_handler)

    await smtp_client.connect()
    await smtp_client.ehlo()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_client.noop()


async def test_connect_with_login(
    smtp_client: SMTP,
    smtpd_server: asyncio.AbstractServer,
    message: email.message.Message,
    received_messages: List[email.message.EmailMessage],
    received_commands: List[Tuple[str, Tuple[Any, ...]]],
    auth_username: str,
    auth_password: str,
) -> None:
    # STARTTLS is required for login
    await smtp_client.connect(
        start_tls=True,
        validate_certs=False,
        username=auth_username,
        password=auth_password,
    )

    assert "AUTH" in [command[0] for command in received_commands]

    await smtp_client.quit()


async def test_connect_via_socket(
    smtp_client: SMTP, hostname: str, smtpd_server_port: int
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((hostname, smtpd_server_port))

        await smtp_client.connect(hostname=None, port=None, sock=sock)
        response = await smtp_client.ehlo()

    assert response.code == SMTPStatus.completed


async def test_connect_via_socket_path(
    smtp_client: SMTP,
    smtpd_server_socket_path: asyncio.AbstractServer,
    socket_path: Union[pathlib.Path, str, bytes],
) -> None:
    await smtp_client.connect(hostname=None, port=None, socket_path=socket_path)
    response = await smtp_client.ehlo()

    assert response.code == SMTPStatus.completed
