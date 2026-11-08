"""Real UDP servers on 127.0.0.1 for testing the clients."""

import asyncio
import socket
import threading
from collections.abc import Container, Generator
from contextlib import contextmanager

from little_a2s.client.types import Address
from tests.constants import A2S_INFO_COUNTERSTRIKE_SOURCE, A2S_PLAYER, S2C_CHALLENGE

CHALLENGE = S2C_CHALLENGE[-4:]
A2S_INFO_REQUEST_HEADER = b"\xff\xff\xff\xffT"


def reply_to(data: bytes, *, always_challenge: bool = False) -> bytes:
    """Challenge requests without the correct challenge, otherwise answer them."""
    if always_challenge or not data.endswith(CHALLENGE):
        return S2C_CHALLENGE
    elif data.startswith(A2S_INFO_REQUEST_HEADER):
        return A2S_INFO_COUNTERSTRIKE_SOURCE
    return A2S_PLAYER


class AsyncServer(asyncio.DatagramProtocol):
    """A UDP server that can drop chosen requests and delay its replies.

    :param drop: The indexes of the received requests to drop, starting from 0.
    :param delay: The number of seconds to wait before sending each reply.
    :param answer_once: If True, drop requests identical to an earlier one.
    :param always_challenge: If True, challenge every request.

    """

    transport: asyncio.DatagramTransport

    def __init__(
        self,
        *,
        drop: Container[int] = frozenset(),
        delay: float = 0,
        answer_once: bool = False,
        always_challenge: bool = False,
    ) -> None:
        self.drop = drop
        self.delay = delay
        self.answer_once = answer_once
        self.always_challenge = always_challenge
        self.requests: list[bytes] = []

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Address) -> None:
        index = len(self.requests)
        repeated = data in self.requests
        self.requests.append(data)
        if index in self.drop or (self.answer_once and repeated):
            return

        reply = reply_to(data, always_challenge=self.always_challenge)
        loop = asyncio.get_running_loop()
        loop.call_later(self.delay, self.transport.sendto, reply, addr)


async def start(server: AsyncServer) -> tuple[str, int]:
    """Serve on a free port of 127.0.0.1 and return the address."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: server,
        local_addr=("127.0.0.1", 0),
    )
    return transport.get_extra_info("sockname")


@contextmanager
def sync_server(
    *,
    drop: Container[int] = frozenset(),
    delay: float = 0,
    answer_once: bool = False,
    always_challenge: bool = False,
) -> Generator[tuple[tuple[str, int], list[bytes]], None, None]:
    """Run a UDP server in a thread, yielding its address and received requests.

    This takes the same options as :class:`AsyncServer`.

    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.05)
    requests: list[bytes] = []
    timers: list[threading.Timer] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except TimeoutError:
                continue
            index = len(requests)
            repeated = data in requests
            requests.append(data)
            if index in drop or (answer_once and repeated):
                continue

            reply = reply_to(data, always_challenge=always_challenge)
            timer = threading.Timer(delay, sock.sendto, (reply, addr))
            timers.append(timer)
            timer.start()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield sock.getsockname(), requests
    finally:
        stop.set()
        thread.join()
        for timer in timers:
            timer.cancel()
            timer.join()
        sock.close()
