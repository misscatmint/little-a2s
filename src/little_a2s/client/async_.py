from __future__ import annotations

import asyncio
import logging
import socket
from collections import OrderedDict
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from types import EllipsisType
from typing import Self, cast

from little_a2s.client.constants import (
    DEFAULT_RESEND_INTERVAL,
    DEFAULT_TIMEOUT,
    MAX_PROTOCOLS,
)
from little_a2s.client.types import Address, ClientEventT, positive_or_none
from little_a2s.errors import ChallengeError
from little_a2s.events import (
    ClientEvent,
    ClientEventChallenge,
    ClientEventGoldsourceInfo,
    ClientEventInfo,
    ClientEventPlayers,
    ClientEventRules,
)
from little_a2s.packets import ClientPacket
from little_a2s.protocol import A2SClientProtocol, A2SGoldsourceClientProtocol

log = logging.getLogger(__name__)


class AsyncA2S(asyncio.DatagramProtocol):
    """An asynchronous client for A2S queries.

    ::

        a2s = AsyncA2S.from_addr("127.0.0.1", 27015)
        async with a2s, asyncio.timeout(1):
            print(await a2s.info())
            print(await a2s.players())
            print(await a2s.rules())

    This follows the Source format. For the Goldsource equivalent,
    see :class:`AsyncA2SGoldsource`.

    This class supports the asynchronous context manager protocol which calls
    the connector function to set the transport + remote address, and closes
    the transport upon exit.

    :param connector:
        The function to call and await to create a datagram transport
        and return the remote address, if any.
        See also :meth:`from_addr()`, :meth:`from_ipv4()`, and :meth:`from_ipv6()`.
    :param timeout:
        The number of seconds each request can take, including any
        challenges and resends, before raising :exc:`TimeoutError`,
        or None to wait indefinitely.
    :param resend_interval:
        The number of seconds to wait for a response before sending
        the request again, or None to send each request only once.
        While resending, a server that keeps sending the same challenge
        does not raise :exc:`ChallengeError`, so the request times out instead.
    :raises ValueError: timeout or resend_interval is not positive.

    .. versionadded:: 0.5.0

    .. versionchanged:: 0.7.0

        Fixed :exc:`PayloadError` not being raised by request methods.

        Concurrent, pending requests to one address can raise the same PayloadError
        if any received packet is malformed.

    .. versionchanged:: 0.8.0

        Added the ``timeout`` and ``resend_interval`` parameters, and a
        ``timeout`` parameter to :meth:`info()`, :meth:`players()` and
        :meth:`rules()`. Requests now time out after 3 seconds and resend
        every 0.5 seconds by default.

    """

    max_protocols = MAX_PROTOCOLS
    """The number of addresses to keep protocol state for, such as challenges.

    Past this, the least recently used addresses are forgotten, and their
    next request starts with a new challenge. Addresses with pending
    requests are always kept.

    .. versionadded:: 0.8.0

    """

    _remote_addr: Address | None = None
    _transport: asyncio.DatagramTransport | None = None
    _protocols: OrderedDict[Address, A2SClientProtocol]
    _requests: dict[
        tuple[Address, type[ClientEvent]],
        asyncio.Future[ClientEvent | None],
    ]
    _close_fut: asyncio.Future[None]

    def __init__(
        self,
        connector: Callable[[Self], Awaitable[Address | None]],
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> None:
        self.connector = connector
        self._timeout = positive_or_none("timeout", timeout)
        self._resend_interval = positive_or_none("resend_interval", resend_interval)

        self._lock = asyncio.Lock()
        self._request_cond = asyncio.Condition(self._lock)
        self._reset()

    def _reset(self) -> None:
        self._protocols = OrderedDict()
        self._requests = {}

        loop = asyncio.get_running_loop()
        self._close_fut = loop.create_future()

    # Connection methods

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, tb):
        await self.close()
        self._reset()

    async def start(self) -> None:
        """Call the connector function to create the datagram transport.

        :raises OSError: The address could not be resolved.
        :raises RuntimeError: The transport is already connected.

        """
        async with self._lock:
            if self._transport is not None:
                raise RuntimeError("Transport already connected")

            self._remote_addr = await self.connector(self)

            if self._transport is None:
                raise RuntimeError("Connector failed to call connection_made()")

    async def close(self) -> None:
        """Close the current datagram transport, raising any exception
        if the connection improperly closed.

        :raises RuntimeError: The transport is not connected.

        """
        self.transport.close()
        return await asyncio.shield(self._close_fut)

    @property
    def transport(self) -> asyncio.DatagramTransport:
        """The current datagram transport.

        :raises RuntimeError: The transport is not connected.

        """
        if self._transport is None:
            raise RuntimeError("Transport not connected")
        return self._transport

    # Constructor methods

    @classmethod
    def from_addr(
        cls,
        host: str,
        port: int,
        *,
        prefer_ipv4: bool = True,
        timeout: float | None = DEFAULT_TIMEOUT,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Resolve the given host and create an A2S query.

        ::

            async with AsyncA2S.from_addr("127.0.0.1", 27015) as a2s, asyncio.timeout(1):
                print(await a2s.info())
                print(await a2s.players())
                print(await a2s.rules())

        :param host: The IPv4 address, IPv6 address, or domain name to query.
        :param port: The port to query.
        :param prefer_ipv4: If True, prefer to resolve hostnames to IPv4 addresses.
        :param timeout: The request timeout. See :class:`AsyncA2S`.
        :param resend_interval: The resend interval. See :class:`AsyncA2S`.

        """
        connector = partial(
            cls._connect_from_addr,
            host=host,
            port=port,
            prefer_ipv4=prefer_ipv4,
        )
        return cls(connector, timeout=timeout, resend_interval=resend_interval)

    async def _connect_from_addr(
        self,
        *,
        host: str,
        port: int,
        prefer_ipv4: bool = True,
    ) -> Address:
        loop = asyncio.get_running_loop()
        addresses = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_DGRAM,
            proto=socket.IPPROTO_UDP,
        )
        if not addresses:
            raise OSError("Address could not be resolved")

        if prefer_ipv4:
            addr = next((a for a in addresses if a[0] == socket.AF_INET), addresses[0])
        else:
            addr = addresses[0]

        family, _, proto, _, addr = addr
        # exclude tuple[int, bytes] from inferred type
        addr = cast(tuple[str, int] | tuple[str, int, int, int], addr)

        await loop.create_datagram_endpoint(
            lambda: self,
            remote_addr=addr[:2],
            family=family,
            proto=proto,
        )
        return addr

    @classmethod
    def from_ipv4(
        cls,
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Create an A2S query with a UDP IPv4 socket not connected to any address.

        This allows you to use the same socket with ``addr`` arguments::

            async with AsyncA2S.from_ipv4() as a2s, asyncio.timeout(1):
                info = await a2s.info(("127.0.0.1", 2303))
                info = await a2s.info(("127.0.0.1", 27015))

        :param timeout: The request timeout. See :class:`AsyncA2S`.
        :param resend_interval: The resend interval. See :class:`AsyncA2S`.

        """
        connector = partial(cls._connect_from_family, family=socket.AF_INET)
        return cls(connector, timeout=timeout, resend_interval=resend_interval)

    @classmethod
    def from_ipv6(
        cls,
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Create an A2S query with a UDP IPv6 socket not connected to any address.

        This allows you to use the same socket with ``addr`` arguments::

            async with AsyncA2S.from_ipv6() as a2s, asyncio.timeout(1):
                info = await a2s.info(("::1", 2303))
                info = await a2s.info(("::1", 27015))

        :param timeout: The request timeout. See :class:`AsyncA2S`.
        :param resend_interval: The resend interval. See :class:`AsyncA2S`.

        """
        connector = partial(cls._connect_from_family, family=socket.AF_INET6)
        return cls(connector, timeout=timeout, resend_interval=resend_interval)

    async def _connect_from_family(self, *, family: socket.AddressFamily) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=("::" if family == socket.AF_INET6 else "0.0.0.0", 0),
            family=family,
            proto=socket.IPPROTO_UDP,
        )

    # Request methods

    async def info(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventInfo:
        """Send an A2S_INFO request and wait for a response.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return await self._send(ClientEventInfo, addr, proto.info, timeout)

    async def players(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventPlayers:
        """Send an A2S_PLAYER request and wait for a response.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return await self._send(ClientEventPlayers, addr, proto.players, timeout)

    async def rules(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventRules:
        """Send an A2S_RULES request and wait for a response.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return await self._send(ClientEventRules, addr, proto.rules, timeout)

    def _get_addr(self, addr: Address | None) -> Address:
        if self._remote_addr and addr:
            raise TypeError("Transport has remote address, addr= is disallowed")
        elif not self._remote_addr and not addr:
            raise TypeError("Transport has no remote address, addr= is required")
        return addr or self._remote_addr  # type: ignore

    def _get_protocol(self, addr: Address) -> A2SClientProtocol:
        """Get the A2S protocol for the given address, creating a new one
        if it doesn't already exist.

        :param addr: The address to bind to.

        """
        proto = self._protocols.get(addr)
        if proto is not None:
            self._protocols.move_to_end(addr)
            return proto

        proto = self._create_protocol()
        self._protocols[addr] = proto
        self._forget_protocols()
        return proto

    def _forget_protocols(self) -> None:
        # Keep the newest address and any with pending requests so replies arrive.
        pending = {addr for addr, _ in self._requests}
        for addr in list(self._protocols)[:-1]:
            if len(self._protocols) <= self.max_protocols:
                break
            if addr not in pending:
                del self._protocols[addr]

    def _create_protocol(self) -> A2SClientProtocol:
        """Create the A2S protocol to manage state.

        This method can be overridden by subclasses.

        """
        return A2SClientProtocol()

    # DatagramProtocol methods

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is None:
            self._close_fut.set_result(None)
        else:
            self._close_fut.set_exception(exc)

    def datagram_received(self, data: bytes, addr: Address) -> None:
        proto = self._protocols.get(addr)
        if proto is None:
            return log.debug("Ignoring unexpected address %r", addr)

        before = proto.challenge
        try:
            proto.receive_datagram(data)
        except Exception as e:  # noqa: BLE001 should be PayloadError, but we'll pass any exception
            return self._set_addr_exception(addr, e)

        events = proto.events_received()
        challenge = None

        for e in events:
            if isinstance(e, ClientEventChallenge):
                challenge = e
                continue

            key = (addr, type(e))
            fut = self._requests.get(key)
            if fut is None or fut.done():
                log.debug("Ignoring unexpected %s", type(e).__name__)
                continue

            fut.set_result(e)

        # Each resend gets its own challenge back, and only the first is news.
        if challenge is None or (
            self._resend_interval is not None and challenge.challenge == before
        ):
            return

        for (fut_addr, _), fut in self._requests.items():
            if addr == fut_addr and not fut.done():
                fut.set_result(None)

    def _set_addr_exception(self, addr: Address, e: BaseException) -> None:
        for (fut_addr, _), fut in self._requests.items():
            if addr == fut_addr and not fut.done():
                fut.set_exception(e)

    async def _send(
        self,
        t: type[ClientEventT],
        addr: Address,
        payload: Callable[[], ClientPacket],
        timeout: float | None | EllipsisType,
    ) -> ClientEventT:
        key = (addr, t)
        limit = self._timeout if isinstance(timeout, EllipsisType) else timeout

        async with asyncio.timeout(limit):
            for _attempt in range(3):
                async with self._claim_request(key) as fut:
                    while True:
                        self.transport.sendto(bytes(payload()), addr)
                        # wait_for() would cancel the future and lose a late reply.
                        done, _pending = await asyncio.wait(
                            {fut}, timeout=self._resend_interval
                        )
                        if done:
                            break
                    event = fut.result()

                if event is not None:
                    return event

        raise ChallengeError("Server responded with too many challenges")

    @asynccontextmanager
    async def _claim_request(
        self,
        key: tuple[Address, type[ClientEvent]],
    ) -> AsyncGenerator[asyncio.Future]:
        loop = asyncio.get_running_loop()

        async with self._request_cond:
            await self._request_cond.wait_for(lambda: key not in self._requests)
            self._requests[key] = fut = loop.create_future()

        try:
            yield fut
        finally:
            async with self._request_cond:
                self._requests.pop(key, None)
                self._request_cond.notify_all()


class AsyncA2SGoldsource(AsyncA2S):
    """A asynchronous client for A2S Goldsource queries."""

    async def info(  # type: ignore
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventGoldsourceInfo:
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return await self._send(ClientEventGoldsourceInfo, addr, proto.info, timeout)

    def _create_protocol(self) -> A2SGoldsourceClientProtocol:
        return A2SGoldsourceClientProtocol()
