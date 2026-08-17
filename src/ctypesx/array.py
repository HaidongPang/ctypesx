"""Typed, checked, zero-copy views over fixed and flexible C arrays."""

from __future__ import annotations

import ctypes
import operator
from collections.abc import Iterable, Iterator, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Protocol,
    Self,
    TypeVar,
    cast,
    overload,
)

_ReadT_co = TypeVar("_ReadT_co", covariant=True)
_WriteT_contra = TypeVar("_WriteT_contra", contravariant=True)
_WriteT = TypeVar("_WriteT")


class _Convertible(Protocol[_WriteT_contra]):
    """Static-only relation between a C value and accepted Python inputs."""

    if TYPE_CHECKING:

        def __set__(
            self,
            instance: object,
            value: _WriteT_contra,
            /,
        ) -> None: ...


_ArrayProvider = Callable[[], ctypes.Array[Any]]
_Reader = Callable[[ctypes.Array[Any], int], Any]
_Coercer = Callable[[Any], Any]
_Committer = Callable[[int, Any], None]
_Replacer = Callable[[Sequence[Any]], None]
_LeaseCallback = Callable[[], None]


class Array(Generic[_ReadT_co]):
    """A mutable fixed-length view over contiguous C array storage.

    ``Array[T]`` is both the public field annotation and the value returned by
    a record field.  Instances are created by the record runtime; constructing
    one directly is intentionally unsupported.
    """

    __slots__ = (
        "__provider",
        "__reader",
        "__coercer",
        "__committer",
        "__pin",
        "__unpin",
    )

    def __init__(
        self,
        provider: _ArrayProvider,
        reader: _Reader,
        coercer: _Coercer,
        committer: _Committer | None = None,
        pin: _LeaseCallback | None = None,
        unpin: _LeaseCallback | None = None,
        /,
    ) -> None:
        if (pin is None) is not (unpin is None):
            raise TypeError("array buffer pin and unpin callbacks must be paired")
        self.__provider = provider
        self.__reader = reader
        self.__coercer = coercer
        self.__committer = committer
        self.__pin = pin
        self.__unpin = unpin

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self: Array[_Convertible[_WriteT]],
            instance: object,
            value: Sequence[_WriteT],
            /,
        ) -> None: ...

    @property
    def raw(self) -> ctypes.Array[Any]:
        """Return the unchecked ctypes array sharing the current storage."""

        return self.__provider()

    @property
    def address(self) -> int:
        """Return the current address of the first array byte."""

        return ctypes.addressof(self.raw)

    @property
    def buffer(self) -> memoryview:
        """Return a writable byte view sharing the current storage."""

        return memoryview(self).cast("B")

    def __buffer__(self, flags: int, /) -> memoryview:
        del flags
        if self.__pin is not None:
            self.__pin()
        try:
            return memoryview(self.raw).cast("B")
        except BaseException:
            if self.__unpin is not None:
                self.__unpin()
            raise

    def __release_buffer__(self, buffer: memoryview, /) -> None:
        del buffer
        if self.__unpin is not None:
            self.__unpin()

    def __len__(self) -> int:
        return len(self.raw)

    def __iter__(self) -> Iterator[_ReadT_co]:
        for index in range(len(self)):
            yield self[index]

    @overload
    def __getitem__(self, index: int, /) -> _ReadT_co: ...

    @overload
    def __getitem__(self, index: slice, /) -> list[_ReadT_co]: ...

    def __getitem__(
        self,
        index: int | slice,
        /,
    ) -> _ReadT_co | list[_ReadT_co]:
        raw = self.raw
        if isinstance(index, slice):
            return [
                cast(_ReadT_co, self.__reader(raw, item))
                for item in range(len(raw))[index]
            ]
        return cast(
            _ReadT_co,
            self.__reader(raw, operator.index(index)),
        )

    @overload
    def __setitem__(
        self: Array[_Convertible[_WriteT]],
        index: int,
        value: _WriteT,
        /,
    ) -> None: ...

    @overload
    def __setitem__(
        self: Array[_Convertible[_WriteT]],
        index: slice,
        value: Iterable[_WriteT],
        /,
    ) -> None: ...

    def __setitem__(
        self,
        index: int | slice,
        value: Any,
        /,
    ) -> None:
        raw = self.raw
        if not isinstance(index, slice):
            self._set_one(operator.index(index), value)
            return

        try:
            source = list(cast(Iterable[Any], value))
        except TypeError:
            raise TypeError("slice assignment requires an iterable") from None
        targets = list(range(len(raw))[index])
        if len(source) != len(targets):
            raise ValueError(
                "fixed C array slice assignment cannot change its length"
            )
        staged = [self.__coercer(item) for item in source]
        for target, converted in zip(targets, staged, strict=True):
            if self.__committer is None:
                raw[target] = converted
            else:
                self.__committer(target, converted)

    def _set_one(self, index: int, value: object, /) -> None:
        converted = self.__coercer(value)
        if self.__committer is None:
            self.raw[index] = converted
        else:
            self.__committer(index, converted)

    def __bytes__(self) -> bytes:
        return bytes(self.buffer)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self)!r})"


class FamArray(Array[_ReadT_co]):
    """A list-like view over the flexible tail of an owning C record.

    Length-changing operations resize an owning record.  A record borrowed
    with ``from_buffer`` has a fixed external extent and therefore accepts
    only equal-length writes.
    """

    __slots__ = ("__replacer",)

    def __init__(
        self,
        provider: _ArrayProvider,
        reader: _Reader,
        coercer: _Coercer,
        replacer: _Replacer,
        committer: _Committer | None = None,
        pin: _LeaseCallback | None = None,
        unpin: _LeaseCallback | None = None,
        /,
    ) -> None:
        super().__init__(provider, reader, coercer, committer, pin, unpin)
        self.__replacer = replacer

    if TYPE_CHECKING:

        def __set__(
            self: FamArray[_Convertible[_WriteT]],
            instance: object,
            value: Sequence[_WriteT],
            /,
        ) -> None: ...

    @overload
    def __setitem__(
        self: FamArray[_Convertible[_WriteT]],
        index: int,
        value: _WriteT,
        /,
    ) -> None: ...

    @overload
    def __setitem__(
        self: FamArray[_Convertible[_WriteT]],
        index: slice,
        value: Iterable[_WriteT],
        /,
    ) -> None: ...

    def __setitem__(
        self,
        index: int | slice,
        value: Any,
        /,
    ) -> None:
        if not isinstance(index, slice):
            self._set_one(operator.index(index), value)
            return

        try:
            replacement = list(cast(Iterable[Any], value))
        except TypeError:
            raise TypeError("slice assignment requires an iterable") from None

        values = cast(list[Any], list(self))
        # list implements the desired extended-slice length validation.
        values[index] = replacement
        self.__replacer(values)

    def __delitem__(self, index: int | slice, /) -> None:
        values = cast(list[Any], list(self))
        del values[index]
        self.__replacer(values)

    def insert(
        self: FamArray[_Convertible[_WriteT]],
        index: int,
        value: _WriteT,
        /,
    ) -> None:
        values = cast(list[Any], list(self))
        values.insert(operator.index(index), value)
        self.__replacer(values)

    def append(
        self: FamArray[_Convertible[_WriteT]],
        value: _WriteT,
        /,
    ) -> None:
        values = cast(list[Any], list(self))
        values.append(value)
        self.__replacer(values)

    def extend(
        self: FamArray[_Convertible[_WriteT]],
        values: Iterable[_WriteT],
        /,
    ) -> None:
        complete = cast(list[Any], list(self))
        complete.extend(values)
        self.__replacer(complete)

    def pop(self, index: int = -1, /) -> _ReadT_co:
        values = cast(list[Any], list(self))
        result = values.pop(operator.index(index))
        self.__replacer(values)
        return result

    def clear(self) -> None:
        self.__replacer(())
