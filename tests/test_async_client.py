import asyncio
import math
import time
from collections.abc import Awaitable, Callable

import pytest

from little_a2s import AsyncA2S, ChallengeError
from little_a2s.events import ClientEventInfo, ClientEventPlayers
from tests.udp_server import CHALLENGE, AsyncServer, start

TIMEOUT = 2
SHORT_TIMEOUT = 0.3
INTERVAL = 0.05
SLOW_REPLY = INTERVAL * 4
EVERY_REQUEST = range(1000)

Query = Callable[[AsyncA2S], Awaitable[ClientEventInfo | ClientEventPlayers]]


def run_query(
    server: AsyncServer,
    query: Query,
    *,
    resend_interval: float | None,
    timeout: float | None = TIMEOUT,
) -> ClientEventInfo | ClientEventPlayers:
    async def main() -> ClientEventInfo | ClientEventPlayers:
        host, port = await start(server)
        try:
            client = AsyncA2S.from_addr(
                host,
                port,
                timeout=timeout,
                resend_interval=resend_interval,
            )
            async with client:
                return await query(client)
        finally:
            server.transport.close()

    return asyncio.run(main())


def info(client: AsyncA2S) -> Awaitable[ClientEventInfo]:
    return client.info()


def players(client: AsyncA2S) -> Awaitable[ClientEventPlayers]:
    return client.players()


each_query = pytest.mark.parametrize("query", [info, players])
each_query_and_event = pytest.mark.parametrize(
    ("query", "event_type"),
    [(info, ClientEventInfo), (players, ClientEventPlayers)],
)


@each_query_and_event
def test_no_resend_no_loss(query: Query, event_type: type) -> None:
    server = AsyncServer()
    assert isinstance(run_query(server, query, resend_interval=None), event_type)
    assert len(server.requests) == 2


@each_query
def test_no_resend_first_request_lost(query: Query) -> None:
    server = AsyncServer(drop={0})
    with pytest.raises(TimeoutError):
        run_query(server, query, resend_interval=None, timeout=SHORT_TIMEOUT)
    assert len(server.requests) == 1


@each_query
def test_no_resend_repeated_challenge_raises(query: Query) -> None:
    server = AsyncServer(always_challenge=True)
    with pytest.raises(ChallengeError):
        run_query(server, query, resend_interval=None)
    assert len(server.requests) == 3


@each_query_and_event
def test_resend_no_loss(query: Query, event_type: type) -> None:
    server = AsyncServer()
    assert isinstance(run_query(server, query, resend_interval=0.2), event_type)
    assert len(server.requests) == 2


@each_query_and_event
def test_resend_first_request_lost(query: Query, event_type: type) -> None:
    server = AsyncServer(drop={0})
    assert isinstance(run_query(server, query, resend_interval=INTERVAL), event_type)
    assert len(server.requests) >= 3


@each_query_and_event
def test_resend_request_after_challenge_lost(query: Query, event_type: type) -> None:
    server = AsyncServer(drop={1})
    assert isinstance(run_query(server, query, resend_interval=INTERVAL), event_type)
    assert len(server.requests) >= 3
    assert server.requests[-1].endswith(CHALLENGE)


@each_query_and_event
def test_resend_reply_slower_than_timer(query: Query, event_type: type) -> None:
    server = AsyncServer(delay=SLOW_REPLY)
    assert isinstance(run_query(server, query, resend_interval=INTERVAL), event_type)
    assert len(server.requests) > 2


@each_query_and_event
def test_resend_late_reply_to_earlier_packet_counts(
    query: Query,
    event_type: type,
) -> None:
    server = AsyncServer(delay=SLOW_REPLY, answer_once=True)
    assert isinstance(run_query(server, query, resend_interval=INTERVAL), event_type)
    assert len(server.requests) > 2


@each_query
def test_resend_repeated_challenge_times_out(query: Query) -> None:
    server = AsyncServer(always_challenge=True)
    with pytest.raises(TimeoutError):
        run_query(server, query, resend_interval=INTERVAL, timeout=SHORT_TIMEOUT)


def test_timeout_ends_resending() -> None:
    async def main() -> float:
        server = AsyncServer(drop=EVERY_REQUEST)
        host, port = await start(server)
        client = AsyncA2S.from_addr(
            host,
            port,
            timeout=SHORT_TIMEOUT,
            resend_interval=INTERVAL,
        )
        async with client:
            start_time = time.monotonic()
            with pytest.raises(TimeoutError):
                await client.players()
            elapsed = time.monotonic() - start_time
        server.transport.close()
        assert len(server.requests) >= 3
        return elapsed

    assert SHORT_TIMEOUT * 0.9 <= asyncio.run(main()) < 1


def test_call_timeout_overrides_client_timeout() -> None:
    async def main() -> float:
        server = AsyncServer(drop=EVERY_REQUEST)
        host, port = await start(server)
        async with AsyncA2S.from_addr(host, port, timeout=TIMEOUT) as client:
            start_time = time.monotonic()
            with pytest.raises(TimeoutError):
                await client.info(timeout=SHORT_TIMEOUT)
            elapsed = time.monotonic() - start_time
        server.transport.close()
        return elapsed

    assert asyncio.run(main()) < 1


def test_call_timeout_none_waits_past_client_timeout() -> None:
    async def main() -> ClientEventPlayers:
        server = AsyncServer(delay=SHORT_TIMEOUT * 2)
        host, port = await start(server)
        client = AsyncA2S.from_addr(
            host,
            port,
            timeout=SHORT_TIMEOUT,
            resend_interval=None,
        )
        async with client:
            event = await client.players(timeout=None)
        server.transport.close()
        return event

    assert isinstance(asyncio.run(main()), ClientEventPlayers)


def test_outer_timeout_still_applies() -> None:
    async def main() -> None:
        server = AsyncServer(drop=EVERY_REQUEST)
        host, port = await start(server)
        client = AsyncA2S.from_addr(host, port, timeout=None)
        async with client:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(SHORT_TIMEOUT):
                    await client.info()
        server.transport.close()

    asyncio.run(main())


def test_defaults_resend_lost_packet() -> None:
    async def main() -> float:
        server = AsyncServer(drop={0})
        host, port = await start(server)
        async with AsyncA2S.from_addr(host, port) as client:
            start_time = time.monotonic()
            await client.players()
            elapsed = time.monotonic() - start_time
        server.transport.close()
        assert len(server.requests) == 3
        return elapsed

    assert 0.45 <= asyncio.run(main()) < 1.5


@pytest.mark.parametrize(
    ("timeout", "resend_interval"),
    [
        (0, 0.5),
        (-1, 0.5),
        (math.nan, 0.5),
        (3, 0),
        (3, -0.5),
        (3, math.nan),
    ],
)
def test_invalid_settings(timeout: float, resend_interval: float) -> None:
    async def main() -> None:
        with pytest.raises(ValueError):
            AsyncA2S.from_addr(
                "127.0.0.1",
                27015,
                timeout=timeout,
                resend_interval=resend_interval,
            )

    asyncio.run(main())
