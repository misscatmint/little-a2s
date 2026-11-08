import logging
import socket
import time
from collections import OrderedDict
from collections.abc import Callable
from types import EllipsisType
from typing import Self

from little_a2s.client.constants import (
    DEFAULT_RESEND_INTERVAL,
    DEFAULT_TIMEOUT,
    MAX_PROTOCOLS,
)
from little_a2s.client.types import Address, ClientEventT, first, positive_or_none
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


class A2S:
    """A synchronous client for A2S queries.

    ::

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("127.0.0.1", 27015))
        with A2S(sock, timeout=1) as a2s:
            print(a2s.info())
            print(a2s.players())
            print(a2s.rules())

    This follows the Source format. For the Goldsource equivalent,
    see :class:`A2SGoldsource`.

    This class supports the context manager protocol which automatically
    closes the socket upon exit.

    This class is not thread-safe.

    :param sock:
        The UDP socket to send and receive queries from.
        The socket can be connected to a remote address beforehand
        with :meth:`~socket.socket.connect()`, if you want to skip
        ``addr`` arguments in send methods. The client sets the socket's
        timeout itself while waiting for responses.
        Alternatively, use :meth:`from_addr()`, :meth:`from_ipv4()`,
        or :meth:`from_ipv6()` to construct the socket for you.
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

    .. versionadded:: 0.2.0

    .. versionchanged:: 0.5.0

        Removed the ``challenge=`` parameter.

    .. versionchanged:: 0.5.0

        Removed the ``events_received()`` method.

    .. versionchanged:: 0.6.0

        Passing a socket that is not of type :data:`socket.SOCK_DGRAM`
        will raise :exc:`TypeError` instead of :exc:`ValueError`.

    .. versionchanged:: 0.8.0

        Added the ``timeout`` and ``resend_interval`` parameters, and a
        ``timeout`` parameter to :meth:`info()`, :meth:`players()` and
        :meth:`rules()`. The timeout now limits each request as a whole
        instead of each wait for a packet, and is no longer set through
        the socket. Requests resend every 0.5 seconds by default.

    """

    buffer_size = 32768  # probably overkill?
    max_protocols = MAX_PROTOCOLS
    """The number of addresses to keep protocol state for, such as challenges.

    Past this, the least recently used addresses are forgotten, and their
    next request starts with a new challenge.

    .. versionadded:: 0.8.0

    """

    _remote_addr: Address | None = None
    _protocols: OrderedDict[Address, A2SClientProtocol]

    def __init__(
        self,
        sock: socket.socket,
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> None:
        if sock.type != socket.SOCK_DGRAM:
            raise TypeError("Socket type must be SOCK_DGRAM")

        self._sock = sock
        self._timeout = positive_or_none("timeout", timeout)
        self._resend_interval = positive_or_none("resend_interval", resend_interval)
        self._remote_addr = None  # FIXME: can this be introspected from sock?
        self._protocols = OrderedDict()

    # Connection methods

    def __enter__(self) -> Self:
        self._sock.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, tb) -> None:
        return self._sock.__exit__(exc_type, exc_val, tb)

    # Constructor methods

    @classmethod
    def from_addr(
        cls,
        host: str,
        port: int,
        timeout: float | None = DEFAULT_TIMEOUT,
        *,
        prefer_ipv4: bool = True,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Resolve the given host and create an A2S query.

        ::

            with A2S.from_addr("127.0.0.1", 27015) as a2s:
                print(a2s.info())
                print(a2s.players())
                print(a2s.rules())

        :param host: The IPv4 address, IPv6 address, or domain name to query.
        :param port: The port to query.
        :param timeout: The request timeout. See :class:`A2S`.
        :param prefer_ipv4:
            If True, prefer to resolve hostnames to IPv4 addresses.
            This may still connect the socket to an IPv6 address so if you
            need more control, consider using :func:`socket.getaddrinfo()`
            to manually create a socket and pass it to the constructor.

            .. versionadded:: 0.2.1
        :param resend_interval: The resend interval. See :class:`A2S`.
        :raises OSError: The address could not be resolved.

        """
        addresses = socket.getaddrinfo(
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

        family, type, proto, _, addr = addr
        sock = socket.socket(family, type, proto)
        sock.connect(addr)

        obj = cls(sock, timeout=timeout, resend_interval=resend_interval)
        obj._remote_addr = addr  # Default address when user calls addr=None
        return obj

    @classmethod
    def from_ipv4(
        cls,
        timeout: float | None = DEFAULT_TIMEOUT,
        *,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Create an A2S query with a UDP IPv4 socket not connected to any address.

        This allows you to use the same socket with ``addr`` arguments::

            with A2S.from_ipv4() as a2s:
                info = a2s.info(("127.0.0.1", 2303))
                info = a2s.info(("127.0.0.1", 27015))

        :param timeout: The request timeout. See :class:`A2S`.
        :param resend_interval: The resend interval. See :class:`A2S`.

        .. versionadded:: 0.4.0

        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        return cls(sock, timeout=timeout, resend_interval=resend_interval)

    @classmethod
    def from_ipv6(
        cls,
        timeout: float | None = DEFAULT_TIMEOUT,
        *,
        resend_interval: float | None = DEFAULT_RESEND_INTERVAL,
    ) -> Self:
        """Create an A2S query with a UDP IPv6 socket not connected to any address.

        This allows you to use the same socket with ``addr`` arguments::

            with A2S.from_ipv6() as a2s:
                info = a2s.info(("::1", 2303))
                info = a2s.info(("::1", 27015))

        :param timeout: The request timeout. See :class:`A2S`.
        :param resend_interval: The resend interval. See :class:`A2S`.

        .. versionadded:: 0.4.0

        """
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        return cls(sock, timeout=timeout, resend_interval=resend_interval)

    # Request methods

    def info(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventInfo:
        """Send an A2S_INFO request and wait for a response.

        .. versionchanged:: 0.5.0

            addr can now be a positional argument.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.

            .. versionadded:: 0.4.0
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

            .. versionadded:: 0.8.0

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return self._send(ClientEventInfo, addr, proto.info, timeout)

    def players(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventPlayers:
        """Send an A2S_PLAYER request and wait for a response.

        .. versionchanged:: 0.5.0

            addr can now be a positional argument.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.

            .. versionadded:: 0.4.0
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

            .. versionadded:: 0.8.0

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return self._send(ClientEventPlayers, addr, proto.players, timeout)

    def rules(
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventRules:
        """Send an A2S_RULES request and wait for a response.

        .. versionchanged:: 0.5.0

            addr can now be a positional argument.

        :param addr:
            The address to send the request to.
            Does not apply if socket is already connected to an address,
            such as from :meth:`from_addr()`.

            .. versionadded:: 0.4.0
        :param timeout:
            The number of seconds this request can take, or None to wait
            indefinitely. Zero or less times out right away.
            Defaults to the client's timeout.

            .. versionadded:: 0.8.0

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.
        :raises TypeError: The addr argument was required or forbidden.

        """
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return self._send(ClientEventRules, addr, proto.rules, timeout)

    def _get_addr(self, addr: Address | None) -> Address:
        if self._remote_addr and addr:
            raise TypeError("Socket has remote address, addr= is disallowed")
        elif not self._remote_addr and not addr:
            raise TypeError("Socket has no remote address, addr= is required")
        return addr or self._remote_addr  # type: ignore

    def _get_protocol(self, addr: Address) -> A2SClientProtocol:
        """Get the A2S protocol for the given address, creating a new one
        if it doesn't already exist.

        :param addr: The address to bind to, or None for the default protocol.

        """
        # NOTE: not thread-safe!
        proto = self._protocols.get(addr)
        if proto is not None:
            self._protocols.move_to_end(addr)
            return proto

        proto = self._create_protocol()
        self._protocols[addr] = proto
        if len(self._protocols) > self.max_protocols:
            self._protocols.popitem(last=False)
        return proto

    def _create_protocol(self) -> A2SClientProtocol:
        """Create the A2S protocol to manage state.

        This method can be overridden by subclasses.

        """
        return A2SClientProtocol()

    def _send(
        self,
        t: type[ClientEventT],
        addr: Address,
        payload: Callable[[], ClientPacket],
        timeout: float | None | EllipsisType,
    ) -> ClientEventT:
        """Use the given request function to generate an outbound packet,
        and wait until the server responds with the given event type.

        This automatically handles challenge responses, re-sending the request
        and waiting again.

        :raises ChallengeError: The server sent too many challenges.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The request took longer than the timeout.

        """
        limit = self._timeout if isinstance(timeout, EllipsisType) else timeout
        deadline = None if limit is None else time.monotonic() + limit
        proto = self._protocols[addr]

        for _attempt in range(3):
            challenge = proto.challenge
            event = self._exchange(t, addr, bytes(payload()), challenge, deadline)
            if event is not None:
                return event

        raise ChallengeError("Server responded with too many challenges")

    def _exchange(
        self,
        t: type[ClientEventT],
        addr: Address,
        data: bytes,
        challenge: int,
        deadline: float | None,
    ) -> ClientEventT | None:
        """Send a request, resending it on an interval, until the server
        responds with the given event or with a new challenge.

        Responses from other addresses or of other types are ignored.

        :param challenge: The challenge number the request was made with.
        :param deadline: The :func:`time.monotonic()` time to give up at.
        :returns: The event, or None if the server sent a new challenge.
        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The deadline passed.

        """
        # NOTE: not thread-safe!
        resend_at = self._send_datagram(data, addr)
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise TimeoutError(f"Server failed to respond with {t.__name__}")
            if resend_at is not None and now >= resend_at:
                resend_at = self._send_datagram(data, addr)
                continue

            waits = [when - now for when in (deadline, resend_at) if when is not None]
            self._sock.settimeout(min(waits, default=None))
            try:
                received, recv_addr = self._sock.recvfrom(self.buffer_size)
            except TimeoutError:
                continue

            events = self._receive_datagram(received, recv_addr)
            if recv_addr != addr:
                continue
            if (found := first(t, events)) is not None:
                return found

            # Each resend gets its own challenge back, and only the first is news.
            new = first(ClientEventChallenge, events)
            if new is not None and not (
                self._resend_interval is not None and new.challenge == challenge
            ):
                return None

    def _send_datagram(self, data: bytes, addr: Address) -> float | None:
        """Send a datagram and return when to resend it, if resending is enabled."""
        if self._remote_addr:
            # macOS rejects sendto() with an address on a connected socket.
            self._sock.send(data)
        else:
            self._sock.sendto(data, addr)

        if self._resend_interval is None:
            return None
        return time.monotonic() + self._resend_interval

    def _receive_datagram(self, data: bytes, addr: Address) -> list[ClientEvent]:
        """Pass the datagram to the protocol and return any generated events.

        :raises PayloadError: The server sent a malformed packet.
        :raises TimeoutError: The socket timed out.

        """
        proto = self._protocols.get(addr)
        if proto is None:
            log.debug("Ignoring data from unexpected address %s", addr)
            return []

        proto.receive_datagram(data)

        return proto.events_received()


class A2SGoldsource(A2S):
    """A synchronous client for A2S Goldsource queries."""

    def info(  # type: ignore
        self,
        addr: Address | None = None,
        *,
        timeout: float | None | EllipsisType = ...,
    ) -> ClientEventGoldsourceInfo:
        addr = self._get_addr(addr)
        proto = self._get_protocol(addr)
        return self._send(ClientEventGoldsourceInfo, addr, proto.info, timeout)

    def _create_protocol(self) -> A2SGoldsourceClientProtocol:
        return A2SGoldsourceClientProtocol()
