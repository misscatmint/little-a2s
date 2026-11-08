import asyncio
import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager

from little_a2s import A2S, AsyncA2S
from little_a2s.client.types import Address
from tests.constants import A2S_INFO_COUNTERSTRIKE_SOURCE, A2S_PLAYER, S2C_CHALLENGE

CHALLENGE = S2C_CHALLENGE[-4:]
A2S_INFO_REQUEST_HEADER = b"\xff\xff\xff\xffT"
OUTER_TIMEOUT = 2


def reply_to(data: bytes) -> bytes:
    """Challenge requests without the correct challenge, otherwise answer them."""
    if not data.endswith(CHALLENGE):
        return S2C_CHALLENGE
    elif data.startswith(A2S_INFO_REQUEST_HEADER):
        return A2S_INFO_COUNTERSTRIKE_SOURCE
    return A2S_PLAYER


class AsyncServer(asyncio.DatagramProtocol):
    """A real UDP server that counts requests and can delay its replies."""

    transport: asyncio.DatagramTransport

    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.requests = 0

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Address) -> None:
        self.requests += 1
        loop = asyncio.get_running_loop()
        loop.call_later(self.delay, self.transport.sendto, reply_to(data), addr)


async def start_servers(*servers: AsyncServer) -> list[Address]:
    loop = asyncio.get_running_loop()
    addrs: list[Address] = []
    for server in servers:
        transport, _ = await loop.create_datagram_endpoint(
            lambda server=server: server,
            local_addr=("127.0.0.1", 0),
        )
        addrs.append(transport.get_extra_info("sockname"))
    return addrs


def test_async_forgets_least_recently_used_address() -> None:
    async def main() -> list[int]:
        servers = [AsyncServer() for _ in range(3)]
        a, b, c = await start_servers(*servers)
        client = AsyncA2S.from_ipv4()
        client.max_protocols = 2
        async with client, asyncio.timeout(OUTER_TIMEOUT):
            for addr in (a, b, a, c, a, b):
                await client.info(addr)
        for server in servers:
            server.transport.close()
        return [server.requests for server in servers]

    # A stays recently used and keeps its challenge, so only its first query
    # is challenged. B is forgotten when C arrives, so it is challenged again.
    assert asyncio.run(main()) == [2 + 1 + 1, 2 + 2, 2]


def test_async_keeps_address_with_pending_request() -> None:
    async def main() -> None:
        slow, fast = AsyncServer(delay=0.3), AsyncServer()
        a, b = await start_servers(slow, fast)
        client = AsyncA2S.from_ipv4()
        client.max_protocols = 1
        async with client, asyncio.timeout(OUTER_TIMEOUT):
            pending = asyncio.create_task(client.players(a))
            await asyncio.sleep(0.1)
            await client.info(b)
            await pending
        slow.transport.close()
        fast.transport.close()

    asyncio.run(main())


@contextmanager
def sync_server() -> Generator[tuple[Address, list[bytes]], None, None]:
    """Run a real UDP server in a thread, yielding its address and requests."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    requests: list[bytes] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except TimeoutError:
                continue
            requests.append(data)
            sock.sendto(reply_to(data), addr)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield sock.getsockname(), requests
    finally:
        stop.set()
        thread.join()
        sock.close()


def test_sync_forgets_least_recently_used_address() -> None:
    with (
        sync_server() as (a, a_requests),
        sync_server() as (b, b_requests),
        sync_server() as (c, c_requests),
        A2S.from_ipv4(timeout=OUTER_TIMEOUT) as client,
    ):
        client.max_protocols = 2
        for addr in (a, b, a, c, a, b):
            client.info(addr)

    assert [len(a_requests), len(b_requests), len(c_requests)] == [4, 4, 2]
