from little_a2s.events import (
    ClientEventChallenge,
    ClientEventGoldsourceInfo,
    ClientEventInfo,
    ClientEventPlayers,
    ClientEventRules,
)
from little_a2s.protocol import A2SClientProtocol
from tests.constants import (
    A2S_INFO_COUNTERSTRIKE_SOURCE,
    A2S_INFO_GOLDSOURCE_COUNTERSTRIKE,
    A2S_INFO_SIN1_MP,
    A2S_PLAYER,
    A2S_RULES_COUNTERSTRIKE_SOURCE_1,
    A2S_RULES_COUNTERSTRIKE_SOURCE_2,
    A2S_RULES_PROJECT_ZOMBOID,
    S2C_CHALLENGE,
)


def test_single_packets() -> None:
    source = A2SClientProtocol()
    source.receive_datagram(S2C_CHALLENGE)
    source.receive_datagram(A2S_INFO_COUNTERSTRIKE_SOURCE)
    source.receive_datagram(A2S_INFO_GOLDSOURCE_COUNTERSTRIKE)
    source.receive_datagram(A2S_INFO_SIN1_MP)
    source.receive_datagram(A2S_PLAYER)
    source.receive_datagram(A2S_RULES_PROJECT_ZOMBOID)

    events = source.events_received()
    assert isinstance(events[0], ClientEventChallenge)
    assert isinstance(events[1], ClientEventInfo)
    assert isinstance(events[2], ClientEventGoldsourceInfo)
    assert isinstance(events[3], ClientEventInfo)
    assert isinstance(events[4], ClientEventPlayers)
    assert isinstance(events[5], ClientEventRules)
    assert len(events) == 6
    assert source.events_received() == []


def test_protocol_challenge() -> None:
    protocol = A2SClientProtocol()
    assert protocol.challenge == -1
    assert protocol.info().challenge == -1
    assert protocol.players().challenge == -1
    assert protocol.rules().challenge == -1

    protocol.receive_datagram(S2C_CHALLENGE)
    assert protocol.challenge == 584425803
    assert protocol.info().challenge == 584425803
    assert protocol.players().challenge == 584425803
    assert protocol.rules().challenge == 584425803


def test_multi_packet_rules() -> None:
    parts = [A2S_RULES_COUNTERSTRIKE_SOURCE_1, A2S_RULES_COUNTERSTRIKE_SOURCE_2]
    for ordered in (parts, parts[::-1]):
        proto = A2SClientProtocol()
        for data in ordered:
            proto.receive_datagram(data)

        events = proto.events_received()
        assert len(events) == 1
        assert isinstance(events[0], ClientEventRules)
        assert len(events[0].rules) == 108
        assert events[0].rules[b"bot_quota"] == b"3"
        assert events[0].rules[b"sm_noblock"] == b"1"
