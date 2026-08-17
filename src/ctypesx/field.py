"""Markers and layout metadata for declarative C record fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _positive_integer(value: object, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{description} must be an integer")
    if value <= 0:
        raise ValueError(f"{description} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Bits:
    """Declare the width of an integer C bit-field."""

    width: int

    def __post_init__(self) -> None:
        _positive_integer(self.width, "bit-field width")


@dataclass(frozen=True, slots=True, init=False)
class Length:
    """Declare the outermost-first dimensions of a fixed C array."""

    dimensions: tuple[int, ...]

    def __init__(self, *dimensions: int) -> None:
        if not dimensions:
            raise TypeError("Length() requires at least one dimension")
        object.__setattr__(
            self,
            "dimensions",
            tuple(
                _positive_integer(dimension, "array dimension")
                for dimension in dimensions
            ),
        )


class _FieldMarker:
    """A class-body marker removed before ctypes compiles ``_fields_``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Field()"


def Field() -> Any:
    """Mark an annotated attribute as a C field.

    The ``Any`` return annotation is deliberate.  Static analyzers treat the
    marker as an ordinary default value while ``@dataclass_transform`` uses
    the declared field annotation for the generated keyword-only constructor.
    Runtime conversion is owned by that annotated C type, not by this marker.
    """

    return _FieldMarker()
