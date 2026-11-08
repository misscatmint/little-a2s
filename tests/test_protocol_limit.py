import asyncio

from little_a2s import A2S, AsyncA2S
from tests.udp_server import AsyncServer, start, sync_server

OUTER_TIMEOUT = 2


def test_async_forgets_least_recently_used_address() -> None:
    async def main() -> list[int]:
        servers = [AsyncServer() for _ in range(3)]
        a, b, c = [await start(server) for server in servers]
        client = AsyncA2S.from_ipv4(resend_interval=None)
        client.max_protocols = 2
        async with client, asyncio.timeout(OUTER_TIMEOUT):
            for addr in (a, b, a, c, a, b):
                await client.info(addr)
        for server in servers:
            server.transport.close()
        return [len(server.requests) for server in servers]

    # A stays recently used and keeps its challenge, so only its first query
    # is challenged. B is forgotten when C arrives, so it is challenged again.
    assert asyncio.run(main()) == [2 + 1 + 1, 2 + 2, 2]


def test_async_keeps_address_with_pending_request() -> None:
    async def main() -> None:
        slow, fast = AsyncServer(delay=0.3), AsyncServer()
        a, b = await start(slow), await start(fast)
        client = AsyncA2S.from_ipv4(resend_interval=None)
        client.max_protocols = 1
        async with client, asyncio.timeout(OUTER_TIMEOUT):
            pending = asyncio.create_task(client.players(a))
            await asyncio.sleep(0.1)
            await client.info(b)
            await pending
        slow.transport.close()
        fast.transport.close()

    asyncio.run(main())


def test_sync_forgets_least_recently_used_address() -> None:
    with (
        sync_server() as (a, a_requests),
        sync_server() as (b, b_requests),
        sync_server() as (c, c_requests),
        A2S.from_ipv4(OUTER_TIMEOUT, resend_interval=None) as client,
    ):
        client.max_protocols = 2
        for addr in (a, b, a, c, a, b):
            client.info(addr)

    assert [len(a_requests), len(b_requests), len(c_requests)] == [4, 4, 2]
