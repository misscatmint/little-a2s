import math
import socket
import time
from collections.abc import Callable

import pytest

from little_a2s import A2S, ChallengeError
from little_a2s.events import ClientEventInfo, ClientEventPlayers
from tests.udp_server import CHALLENGE, sync_server

TIMEOUT = 2
SHORT_TIMEOUT = 0.3
INTERVAL = 0.05
SLOW_REPLY = INTERVAL * 4
EVERY_REQUEST = range(1000)

Query = Callable[[A2S], ClientEventInfo | ClientEventPlayers]


def connect(
    addr: tuple[str, int],
    *,
    resend_interval: float | None,
    timeout: float | None = TIMEOUT,
) -> A2S:
    host, port = addr
    return A2S.from_addr(host, port, timeout, resend_interval=resend_interval)


def info(client: A2S) -> ClientEventInfo:
    return client.info()


def players(client: A2S) -> ClientEventPlayers:
    return client.players()


each_query = pytest.mark.parametrize("query", [info, players])
each_query_and_event = pytest.mark.parametrize(
    ("query", "event_type"),
    [(info, ClientEventInfo), (players, ClientEventPlayers)],
)


def test_from_addr_queries_connected_socket() -> None:
    with sync_server() as (addr, _requests), connect(addr, resend_interval=None) as a2s:
        assert isinstance(a2s.info(), ClientEventInfo)


def test_from_ipv4_queries_given_address() -> None:
    with sync_server() as (addr, _requests), A2S.from_ipv4(TIMEOUT) as a2s:
        assert isinstance(a2s.info(addr), ClientEventInfo)


@each_query_and_event
def test_no_resend_no_loss(query: Query, event_type: type) -> None:
    with sync_server() as (addr, requests), connect(addr, resend_interval=None) as a2s:
        assert isinstance(query(a2s), event_type)
    assert len(requests) == 2


@each_query
def test_no_resend_first_request_lost(query: Query) -> None:
    with (
        sync_server(drop={0}) as (addr, requests),
        connect(addr, resend_interval=None, timeout=SHORT_TIMEOUT) as a2s,
        pytest.raises(TimeoutError),
    ):
        query(a2s)
    assert len(requests) == 1


@each_query
def test_no_resend_repeated_challenge_raises(query: Query) -> None:
    with (
        sync_server(always_challenge=True) as (addr, requests),
        connect(addr, resend_interval=None) as a2s,
        pytest.raises(ChallengeError),
    ):
        query(a2s)
    assert len(requests) == 3


@each_query_and_event
def test_resend_no_loss(query: Query, event_type: type) -> None:
    with sync_server() as (addr, requests), connect(addr, resend_interval=0.2) as a2s:
        assert isinstance(query(a2s), event_type)
    assert len(requests) == 2


@each_query_and_event
def test_resend_first_request_lost(query: Query, event_type: type) -> None:
    with (
        sync_server(drop={0}) as (addr, requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        assert isinstance(query(a2s), event_type)
    assert len(requests) >= 3


@each_query_and_event
def test_resend_request_after_challenge_lost(query: Query, event_type: type) -> None:
    with (
        sync_server(drop={1}) as (addr, requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        assert isinstance(query(a2s), event_type)
    assert len(requests) >= 3
    assert requests[-1].endswith(CHALLENGE)


@each_query_and_event
def test_resend_reply_slower_than_timer(query: Query, event_type: type) -> None:
    with (
        sync_server(delay=SLOW_REPLY) as (addr, requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        assert isinstance(query(a2s), event_type)
    assert len(requests) > 2


@each_query_and_event
def test_resend_late_reply_to_earlier_packet_counts(
    query: Query,
    event_type: type,
) -> None:
    with (
        sync_server(delay=SLOW_REPLY, answer_once=True) as (addr, requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        assert isinstance(query(a2s), event_type)
    assert len(requests) > 2


@each_query
def test_resend_repeated_challenge_times_out(query: Query) -> None:
    with (
        sync_server(always_challenge=True) as (addr, _requests),
        connect(addr, resend_interval=INTERVAL, timeout=SHORT_TIMEOUT) as a2s,
        pytest.raises(TimeoutError),
    ):
        query(a2s)


def test_late_duplicate_reply_does_not_end_next_request() -> None:
    # Resent info() requests get duplicate replies after info() returns.
    with (
        sync_server(delay=SLOW_REPLY) as (addr, _requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        assert isinstance(a2s.info(), ClientEventInfo)
        assert isinstance(a2s.players(), ClientEventPlayers)


def test_timeout_ends_resending() -> None:
    with (
        sync_server(drop=EVERY_REQUEST) as (addr, requests),
        connect(addr, resend_interval=INTERVAL, timeout=SHORT_TIMEOUT) as a2s,
    ):
        start_time = time.monotonic()
        with pytest.raises(TimeoutError):
            a2s.players()
        elapsed = time.monotonic() - start_time
    assert len(requests) >= 3
    assert SHORT_TIMEOUT * 0.9 <= elapsed < 1


def test_call_timeout_overrides_client_timeout() -> None:
    with (
        sync_server(drop=EVERY_REQUEST) as (addr, _requests),
        connect(addr, resend_interval=INTERVAL) as a2s,
    ):
        start_time = time.monotonic()
        with pytest.raises(TimeoutError):
            a2s.info(timeout=SHORT_TIMEOUT)
        elapsed = time.monotonic() - start_time
    assert elapsed < 1


def test_call_timeout_none_waits_past_client_timeout() -> None:
    with (
        sync_server(delay=SHORT_TIMEOUT * 2) as (addr, _requests),
        connect(addr, resend_interval=None, timeout=SHORT_TIMEOUT) as a2s,
    ):
        assert isinstance(a2s.players(timeout=None), ClientEventPlayers)


def test_defaults_resend_lost_packet() -> None:
    with sync_server(drop={0}) as (addr, requests), A2S.from_addr(*addr) as a2s:
        start_time = time.monotonic()
        a2s.players()
        elapsed = time.monotonic() - start_time
    assert len(requests) == 3
    assert 0.45 <= elapsed < 1.5


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
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(ValueError),
    ):
        A2S(sock, timeout=timeout, resend_interval=resend_interval)
