import logging
from dataclasses import dataclass, field
from typing import assert_never

from little_a2s.errors import PayloadError
from little_a2s.events import (
    ClientEvent,
    ClientEventChallenge,
    ClientEventGoldsourceInfo,
    ClientEventInfo,
    ClientEventPlayers,
    ClientEventRules,
)
from little_a2s.headers import (
    Compression,
    Header,
    HeaderType,
    MultiGoldsourceHeader,
    MultiHeader,
    SimpleHeader,
)
from little_a2s.packets import (
    ClientPacketInfo,
    ClientPacketPlayers,
    ClientPacketRules,
)
from little_a2s.reader import Reader

MultiAnyHeader = MultiHeader | MultiGoldsourceHeader

log = logging.getLogger(__name__)


@dataclass(kw_only=True)
class MultiPartResponse:
    """A multi-part response waiting to be assembled.

    .. versionchanged:: 0.2.0

        Removed the ``current`` attribute.

    """

    id: int
    """Unique number assigned by server per answer."""
    total: int
    """The total number of packets in the response."""
    compressed: Compression | None
    """An optional compression header. Mostly present in ~2006-era engines."""
    payloads: dict[int, bytes] = field(default_factory=dict)
    """A sequenced mapping of payloads to be assembled."""

    def add(self, header: MultiAnyHeader, payload: bytes) -> None:
        """Add a payload with the given header to the response.

        :raises PayloadError: The data is malformed.

        """
        if header.id != self.id:
            raise PayloadError(f"Expected ID {self.id!r}, got {header.id!r}")
        elif header.total != self.total:
            raise PayloadError(f"Expected total {self.total!r}, got {header.total!r}")
        elif not 0 <= header.current < self.total:
            raise PayloadError(
                f"Expected current in range [0, {self.total!r}), got {header.current!r}"
            )
        elif header.current in self.payloads:
            raise PayloadError(f"Duplicate current index {header.current!r}")

        self.payloads[header.current] = payload

    def assemble(self) -> bytes | None:
        """Assemble the payload together if all parts have been received.

        :raises PayloadError: The data is malformed.

        """
        if len(self.payloads) < self.total:
            return

        payload = b"".join(self.payloads[i] for i in range(self.total))
        if not self.compressed:
            return payload

        return self._decompress_payload(payload)

    def _decompress_payload(self, payload: bytes) -> bytes:
        import bz2
        import zlib

        assert self.compressed is not None
        size = self.compressed.size
        checksum = self.compressed.checksum

        log.debug("Decompressing bz2 payload")
        payload = bz2.decompress(payload)

        if len(payload) != size:
            raise PayloadError(f"Expected payload size {size}, got {len(payload)}")
        elif zlib.crc32(payload) != checksum:
            raise PayloadError(f"Expected checksum {checksum:X}, got {payload:X}")

        return payload


class A2SClientProtocol:
    """Implements the client-side protocol for A2S.

    This follows the Source format. For the Goldsource equivalent,
    see :class:`A2SGoldsourceClientProtocol`.

    :param challenge:
        The challenge sequence to use for requests.
        This can change dynamically when receiving S2C_CHALLENGE responses.

    .. versionchanged:: 0.7.0

        Removed the ``packets_to_send()`` method.

    """

    _events: list[ClientEvent]
    _responses: dict[int, MultiPartResponse]

    def __init__(self, *, challenge: int = -1) -> None:
        self.challenge = challenge

        self._events = []
        self._responses = {}

    def __repr__(self) -> str:
        type_ = type(self).__name__
        challenge = self.challenge
        events = len(self._events)
        return f"<{type_} {challenge=}, {events} events>"

    def receive_datagram(self, data: bytes) -> None:
        """Process a packet from the server.

        :raises PayloadError: The data is malformed.

        """
        log.debug("Receiving datagram: %r", data)
        reader = Reader(data)

        try:
            header = self._parse_header(reader)
            payload = self._parse_payload(reader, header)
            if payload is not None:
                self._handle_payload(payload)
        except EOFError as e:
            raise PayloadError("Received incomplete data") from e
        except ValueError as e:
            raise PayloadError("Received malformed data") from e

    def events_received(self) -> list[ClientEvent]:
        """Return a list of events received since this last call."""
        current_events, self._events = self._events, []
        return current_events

    def info(self) -> ClientPacketInfo:
        """Create an A2S_INFO packet to send to the server."""
        return ClientPacketInfo(challenge=self.challenge)

    def players(self) -> ClientPacketPlayers:
        """Create an A2S_PLAYER packet to send to the server."""
        return ClientPacketPlayers(challenge=self.challenge)

    def rules(self) -> ClientPacketRules:
        """Create an A2S_RULES packet to send to the server."""
        return ClientPacketRules(challenge=self.challenge)

    def invalidate_response(self, id: int) -> MultiPartResponse | None:
        """Invalidate an incomplete multi-part response with the given ID.

        This should be invoked after some sort of timeout.

        """
        response = self._responses.pop(id, None)
        if response:
            log.debug("Invalidated response %d", response.id)
        return response

    def _parse_header(self, reader: Reader) -> Header:
        type = HeaderType(reader.read_long())
        if type == HeaderType.SIMPLE:
            log.debug("Parsing simple header")
            return self._parse_simple_header(reader)
        elif type == HeaderType.MULTI:
            log.debug("Parsing multi-packet header")
            return self._parse_multi_header(reader)
        else:
            assert_never(type)

    def _parse_simple_header(self, reader: Reader) -> Header:
        return SimpleHeader()

    def _parse_multi_header(self, reader: Reader) -> Header:
        # Source format
        id = reader.read_ulong()
        total = reader.read_byte()
        current = reader.read_byte()
        size = reader.read_ushort()  # Some games omit this field!

        if id >> 15:
            # Our crc32() function returns an unsigned int, so we need ulong here.
            log.debug("Payload is marked as compressed")
            decompressed_size = reader.read_ulong()
            checksum = reader.read_ulong()
            compressed = Compression(size=decompressed_size, checksum=checksum)
        else:
            compressed = None

        return MultiHeader(
            id=id,
            current=current,
            total=total,
            size=size,
            compressed=compressed,
        )

    def _parse_payload(self, reader: Reader, header: Header) -> bytes | None:
        if isinstance(header, SimpleHeader):
            return reader.read()
        elif isinstance(header, MultiHeader):
            log.debug("Parsing multi-packet payload")
            return self._parse_multi_payload(reader, header)
        elif isinstance(header, MultiGoldsourceHeader):
            log.debug("Parsing Goldsource multi-packet payload")
            return self._parse_multi_payload(reader, header)
        else:
            raise PayloadError(f"Unknown header type {header!r}")

    def _parse_multi_payload(
        self,
        reader: Reader,
        header: MultiAnyHeader,
    ) -> bytes | None:
        response = self._get_response(header)
        payload = self._update_response(reader, header, response)
        if payload is None:
            return None
        # Servers repeat the single-packet header at the start of the first part.
        return payload.removeprefix(b"\xff\xff\xff\xff")

    def _get_response(
        self,
        header: MultiAnyHeader,
    ) -> MultiPartResponse:
        response = self._responses.get(header.id)
        if response is not None:
            log.debug("Found previous response %d", response.id)
            return response

        log.debug("Creating new response %d", header.id)
        compressed = header.compressed if isinstance(header, MultiHeader) else None
        response = MultiPartResponse(
            id=header.id,
            total=header.total,
            compressed=compressed,
        )
        self._responses[header.id] = response
        return response

    def _update_response(
        self,
        reader: Reader,
        header: MultiAnyHeader,
        response: MultiPartResponse,
    ) -> bytes | None:
        payload = reader.read()

        log.debug("Adding payload part %d of %d", header.current + 1, header.total)
        try:
            response.add(header, payload)
        except ValueError:
            self.invalidate_response(header.id)
            raise

        payload = response.assemble()
        if payload is not None:
            self.invalidate_response(header.id)
            log.debug("Successfully assembled payload")
            return payload

    def _handle_payload(self, data: bytes) -> None:
        reader = Reader(data)

        header = reader.read_byte()
        if header == 0x41:  # S2C_CHALLENGE
            log.debug("Parsing S2C_CHALLENGE payload")
            event = ClientEventChallenge.from_reader(reader)
            self.challenge = event.challenge
        elif header == 0x49:  # A2S_INFO
            log.debug("Parsing A2S_INFO payload")
            event = ClientEventInfo.from_reader(reader)
        elif header == 0x6D:  # Goldsource A2S_INFO
            log.debug("Parsing Goldsource A2S_INFO payload")
            event = ClientEventGoldsourceInfo.from_reader(reader)
        elif header == 0x44:  # A2S_PLAYER
            log.debug("Parsing A2S_PLAYER payload")
            event = ClientEventPlayers.from_reader(reader)
        elif header == 0x45:  # A2S_RULES
            log.debug("Parsing A2S_RULES payload")
            event = ClientEventRules.from_reader(reader)
        else:
            raise PayloadError(f"Unknown payload header type {header:X}")

        log.debug("Appending event: %s", type(event).__name__)
        self._events.append(event)


class A2SGoldsourceClientProtocol(A2SClientProtocol):
    """The Goldsource variant of the A2S client protocol used by older games.

    .. versionchanged:: 0.2.0

        Renamed to A2SGoldsourceClientProtocol from A2SClientGoldsourceProtocol.

    """

    def _parse_multi_header(self, reader: Reader) -> Header:
        id = reader.read_ulong()
        number = reader.read_byte()
        current = number & 0xF0
        total = number & 0x0F
        return MultiGoldsourceHeader(id=id, current=current, total=total)
