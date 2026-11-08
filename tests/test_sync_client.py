import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager

from little_a2s import A2S
from little_a2s.events import ClientEventInfo
from tests.constants import A2S_INFO_COUNTERSTRIKE_SOURCE, S2C_CHALLENGE

CHALLENGE = S2C_CHALLENGE[-4:]


@contextmanager
def info_server() -> Generator[tuple[str, int], None, None]:
    """Run a real UDP server in a thread that challenges, then answers info."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except TimeoutError:
                continue
            reply = (
                A2S_INFO_COUNTERSTRIKE_SOURCE
                if data.endswith(CHALLENGE)
                else S2C_CHALLENGE
            )
            sock.sendto(reply, addr)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield sock.getsockname()
    finally:
        stop.set()
        thread.join()
        sock.close()


def test_from_addr_queries_connected_socket() -> None:
    with info_server() as (host, port), A2S.from_addr(host, port, timeout=2) as client:
        assert isinstance(client.info(), ClientEventInfo)


def test_from_ipv4_queries_given_address() -> None:
    with info_server() as addr, A2S.from_ipv4(timeout=2) as client:
        assert isinstance(client.info(addr), ClientEventInfo)
