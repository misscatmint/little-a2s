from collections.abc import Iterable, Iterator
from typing import TypeVar

from little_a2s.events import ClientEvent

Address = tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]
T = TypeVar("T")
ClientEventT = TypeVar("ClientEventT", bound=ClientEvent)


def filter_type(
    t: type[T] | tuple[type[T], ...],
    it: Iterable[object],
    /,
) -> Iterator[T]:
    """Filter through an iterable for elements of the given type.

    .. versionadded:: 0.2.0

    """
    for x in it:
        if isinstance(x, t):
            yield x


def first(t: type[T] | tuple[type[T], ...], it: Iterable[object], /) -> T | None:
    """Return the first element of the given type in an iterable.

    .. versionadded:: 0.2.0

    """
    return next(filter_type(t, it), None)


def positive_or_none(name: str, value: float | None) -> float | None:
    """Return the value if it is positive or None.

    :raises ValueError: The value is zero, negative, or NaN.

    .. versionadded:: 0.8.0

    """
    if value is not None and not value > 0:
        raise ValueError(f"{name} must be positive or None, got {value!r}")
    return value


def last(t: type[T] | tuple[type[T], ...], it: Iterable[object], /) -> T | None:
    """Return the last element of the given type in an iterable.

    .. versionadded:: 0.2.0

    """
    x = None
    for x in filter_type(t, it):
        pass
    return x
