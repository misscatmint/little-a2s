from collections.abc import ItemsView, Iterator, KeysView, Mapping, Sequence, ValuesView
from dataclasses import dataclass
from enum import IntEnum
from typing import (
    Self,
    SupportsIndex,
    overload,
)

from little_a2s.enums import _EnumReprMixin
from little_a2s.reader import Reader


# ClientEventInfo types
class ServerType(_EnumReprMixin, IntEnum):
    """Indicates the type of server."""

    DEDICATED = ord("d")
    LISTEN = ord("l")
    RELAY = ord("p")


class Environment(_EnumReprMixin, IntEnum):
    """Indicates the operating system of the server."""

    LINUX = ord("l")
    WINDOWS = ord("w")
    MACOS_M = ord("m")  # Ergh, can this be combined?
    MACOS_O = ord("o")


class Visibility(_EnumReprMixin, IntEnum):
    """Indicates whether the server requires a password."""

    PUBLIC = 0
    PRIVATE = 1


class VAC(_EnumReprMixin, IntEnum):
    """Specifies whether the server uses Valve Anti Cheat."""

    INSECURE = 0
    SECURE = 1


@dataclass(kw_only=True)
class ExtraInfo:
    """Extra data included with an A2S_INFO response."""

    port: int | None = None
    """The server's game port number."""
    steam_id: int | None = None
    """The server's steam ID."""
    spectator_port: int | None = None
    """The spectator port number for SourceTV."""
    spectator_name: str | None = None
    """The name of the spectator server for SourceTV."""
    keywords: str | None = None
    """Tags that describe the game according to the server."""
    game_id: int | None = None
    """The server's game ID. Its low 24 bits are the game's Steam Application ID."""

    @classmethod
    def from_reader(cls, reader: Reader, flag: int) -> Self:
        """Parse this class from a reader.

        :param reader: The reader to consume.
        :param flag: The Extra Data Flag (EDF) indicating which fields are included.

        """
        extra = cls()
        if flag & 0x80:
            extra.port = reader.read_ushort()
        if flag & 0x10:
            extra.steam_id = reader.read_uint64()
        if flag & 0x40:
            extra.spectator_port = reader.read_ushort()
            extra.spectator_name = reader.read_null_utf8()
        if flag & 0x20:
            extra.keywords = reader.read_null_utf8()
        if flag & 0x01:
            extra.game_id = reader.read_uint64()
        return extra


# ClientEventGoldsourceInfo types
class GoldsourceModType(_EnumReprMixin, IntEnum):
    """Indicates the type of mod for :class:`GoldsourceMod`."""

    SINGLE_AND_MULTIPLAYER = 0
    MULTIPLAYER_ONLY = 1


class GoldsourceModDLL(_EnumReprMixin, IntEnum):
    """Indicates whether a :class:`GoldsourceMod` uses its own DLL."""

    NATIVE = 0
    """This mod uses the Half-Life DLL."""

    EXTENSION = 1
    """This mod provides its own DLL."""


@dataclass(kw_only=True)
class GoldsourceMod:
    """Information about the Goldsource mod, if the game is a mod."""

    link: str
    """URL to mod website. May be empty."""
    download_link: str
    """URL to download the mod. May be empty."""
    version: int
    """Version of mod installed on server."""
    size: int
    """Space (in bytes) the mod takes up."""
    type: GoldsourceModType
    """Indicates the type of mod."""
    dll: GoldsourceModDLL
    """Indicates whether the mod uses its own DLL."""

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        link = reader.read_null_utf8()
        download_link = reader.read_null_utf8()
        reader.read_null()
        version = reader.read_ulong()
        size = reader.read_ulong()
        type = GoldsourceModType(reader.read_byte())
        dll = GoldsourceModDLL(reader.read_byte())

        return cls(
            link=link,
            download_link=download_link,
            version=version,
            size=size,
            type=type,
            dll=dll,
        )


# ClientEventPlayer types
@dataclass(kw_only=True)
class Player:
    """A player returned in the A2S_PLAYER response."""

    index: int
    """Index of player."""
    name: str
    """Name of the player."""
    score: int
    """Player's score, such as kills."""
    duration: float
    """Time (in seconds) player has been connected to the server."""


# Event types
@dataclass(kw_only=True)
class Event:
    """The base class for all A2S protocol events."""


@dataclass(kw_only=True)
class ClientEvent(Event):
    """An A2S client protocol event."""


@dataclass(kw_only=True)
class ClientEventInfo(ClientEvent):
    """An A2S_INFO client protocol event.

    This follows the Source format. For the Goldsource equivalent,
    see :class:`ClientEventGoldsourceInfo`.

    """

    protocol: int
    """Protocol version used by the server."""
    name: str
    """Name of the server."""
    map: str
    """Map the server has currently loaded."""
    folder: str
    """Name of the folder containing the game files."""
    game: str
    """Full name of the game."""
    id: int
    """Steam Application ID of game.

    This is a 16-bit field, so servers for games with larger IDs send 0 here.
    Use :attr:`app_id` for the game's actual ID.

    """
    players: int
    """Number of players on the server."""
    max_players: int
    """Maximum number of players the server reports it can hold."""
    bots: int
    """Number of bots on the server. """
    type: ServerType
    """Indicates the type of server."""
    environment: Environment
    """Indicates the operating system of the server."""
    visibility: Visibility
    """Indicates whether the server requires a password."""
    vac: VAC
    """Specifies whether the server uses Valve Anti Cheat."""
    version: str
    """Version of the game installed on the server."""
    extra: ExtraInfo | None
    """Extra data included with the response."""

    @property
    def app_id(self) -> int:
        """Steam Application ID of game.

        This is the low 24 bits of :attr:`ExtraInfo.game_id` when the server
        includes it, and :attr:`id` otherwise.

        .. versionadded:: 0.8.0

        """
        if self.extra is not None and self.extra.game_id is not None:
            return self.extra.game_id & 0xFFFFFF
        return self.id

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        protocol = reader.read_byte()
        name = reader.read_null_utf8()
        map = reader.read_null_utf8()
        folder = reader.read_null_utf8()
        game = reader.read_null_utf8()
        id = reader.read_ushort()
        players = reader.read_byte()
        max_players = reader.read_byte()
        bots = reader.read_byte()
        type = ServerType(reader.read_byte())
        environment = Environment(reader.read_byte())
        visibility = Visibility(reader.read_byte())
        vac = VAC(reader.read_byte())
        # Extra data will be here for The Ship
        version = reader.read_null_utf8()

        try:
            extra_flag = reader.read_byte()
        except EOFError:
            extra = None
        else:
            extra = ExtraInfo.from_reader(reader, extra_flag)

        return cls(
            protocol=protocol,
            name=name,
            map=map,
            folder=folder,
            game=game,
            id=id,
            players=players,
            max_players=max_players,
            bots=bots,
            type=type,
            environment=environment,
            visibility=visibility,
            vac=vac,
            version=version,
            extra=extra,
        )


@dataclass(kw_only=True)
class ClientEventGoldsourceInfo(ClientEvent):
    """An A2S_INFO Goldsource client protocol event."""

    address: str
    """IP address and port of the server."""
    name: str
    """Name of the server."""
    map: str
    """Map the server has currently loaded."""
    folder: str
    """Name of the folder containing the game files."""
    game: str
    """Full name of the game."""
    players: int
    """Number of players on the server."""
    max_players: int
    """Maximum number of players the server reports it can hold."""
    protocol: int
    """Protocol version used by the server."""
    type: ServerType
    """Indicates the type of server."""
    environment: Environment
    """Indicates the operating system of the server."""
    visibility: Visibility
    """Indicates whether the server requires a password."""
    mod: GoldsourceMod | None
    """Information about the Goldsource mod, if the game is a mod."""
    vac: VAC
    """Specifies whether the server uses Valve Anti Cheat."""
    bots: int
    """Number of bots on the server. """

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        address = reader.read_null_utf8()
        name = reader.read_null_utf8()
        map = reader.read_null_utf8()
        folder = reader.read_null_utf8()
        game = reader.read_null_utf8()
        players = reader.read_byte()
        max_players = reader.read_byte()
        protocol = reader.read_byte()
        type = ServerType(ord(reader.read_char().lower()))
        environment = Environment(ord(reader.read_char().lower()))
        visibility = Visibility(reader.read_byte())
        mod = GoldsourceMod.from_reader(reader) if reader.read_byte() == 1 else None
        vac = VAC(reader.read_byte())
        bots = reader.read_byte()

        return cls(
            address=address,
            name=name,
            map=map,
            folder=folder,
            game=game,
            players=players,
            max_players=max_players,
            protocol=protocol,
            type=type,
            environment=environment,
            visibility=visibility,
            mod=mod,
            vac=vac,
            bots=bots,
        )


@dataclass(kw_only=True)
class ClientEventPlayers(ClientEvent, Sequence[Player]):
    """An A2S_PLAYER client protocol event.

    .. versionchanged:: 0.5.1

        Added support for the sequence protocol to interact with
        the underlying list of players.

    .. versionchanged:: 0.8.0

        Stop at the end of the data or at an entry that is all zeros, instead
        of raising :exc:`PayloadError`, when a server cuts a long list short
        or pads the rest of the packet with zeros. The list can then hold
        fewer players than the server is running, so use
        :class:`ClientEventInfo` for an accurate count.

    """

    players: list[Player]
    """List of players whose information was gathered."""

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        players = []
        for _ in range(reader.read_byte()):
            # Servers with long lists can stop early and pad the rest with zeros.
            try:
                index = reader.read_byte()
                name = reader.read_null_utf8()
                score = reader.read_long()
                duration = reader.read_float()
            except EOFError:
                break
            if not (index or name or score or duration):
                break
            # Extra data will be here for The Ship
            player = Player(index=index, name=name, score=score, duration=duration)
            players.append(player)

        return cls(players=players)

    def __contains__(self, item: object) -> bool:
        return item in self.players

    @overload
    def __getitem__(self, index: SupportsIndex) -> Player: ...
    @overload
    def __getitem__(self, index: slice) -> list[Player]: ...
    def __getitem__(self, index):
        return self.players[index]

    def __iter__(self) -> Iterator[Player]:
        yield from self.players

    def __len__(self) -> int:
        return len(self.players)


@dataclass(kw_only=True)
class ClientEventRules(ClientEvent, Mapping[bytes, bytes]):
    """An A2S_RULES client protocol event.

    .. versionchanged:: 0.5.1

        Added support for the mapping protocol to interact with
        the underlying dictionary of rules.

    """

    rules: dict[bytes, bytes]
    """The server rules or configuration variables.

    While the protocol states these should be UTF-8 strings, some games might
    provide binary data in rules which may not decode correctly as UTF-8.
    If you know the game doesn't do this, you can use the :meth:`decode()`
    method for convenience.

    """

    def decode(self) -> dict[str, str]:
        """Return all rules decoded with UTF-8."""
        return {k.decode(): v.decode() for k, v in self.rules.items()}

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        rules = {}
        for _ in range(reader.read_ushort()):
            name = reader.read_null_string()
            value = reader.read_null_string()
            rules[name] = value

        return cls(rules=rules)

    def __contains__(self, item: object) -> bool:
        return item in self.rules

    def __getitem__(self, index: bytes) -> bytes:
        return self.rules[index]

    def __iter__(self) -> Iterator[bytes]:
        yield from self.rules

    def __len__(self) -> int:
        return len(self.rules)

    def keys(self) -> KeysView[bytes]:
        return self.rules.keys()

    def items(self) -> ItemsView[bytes, bytes]:
        return self.rules.items()

    def values(self) -> ValuesView[bytes]:
        return self.rules.values()


@dataclass(kw_only=True)
class ClientEventChallenge(ClientEvent):
    """An S2C_CHALLENGE client protocol event."""

    challenge: int
    """The challenge number to append to subsequent requests."""

    @classmethod
    def from_reader(cls, reader: Reader) -> Self:
        """Parse this class from a reader."""
        return cls(challenge=reader.read_long())
