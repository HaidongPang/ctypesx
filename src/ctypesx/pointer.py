"""Typed pointers, C string pointers, callbacks, and bounded pointer views.

The classes in this module intentionally keep two pointer origins distinct:

* an integer is interpreted as an unverified native address; and
* a sequence is converted to a newly allocated, owned C array.

An owned pointer stores its backing object in ctypes' ``_objects`` graph (via
``ctypes.cast``), not only in an ordinary Python attribute.  Consequently the
backing allocation also survives when ctypes copies the pointer into a
structure field.
"""

from __future__ import annotations

import ctypes
import operator
from collections.abc import Callable, Iterator, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Never,
    ParamSpec,
    Protocol,
    Self,
    SupportsComplex,
    SupportsFloat,
    SupportsIndex,
    TypeVar,
    cast,
    overload,
)


_ElementT_co = TypeVar("_ElementT_co", covariant=True)
_WriteT = TypeVar("_WriteT")
_WriteT_contra = TypeVar("_WriteT_contra", contravariant=True)
_ResultT_co = TypeVar("_ResultT_co", covariant=True)
_Params = ParamSpec("_Params")


class _Convertible(Protocol[_WriteT_contra]):
    """Typing-only protocol used to recover a field's accepted input type."""

    if TYPE_CHECKING:

        def __set__(
            self, instance: object, value: _WriteT_contra, /
        ) -> None: ...


class _CtypesxValue(Protocol):
    """Static shape required for an inferred ctypesx pointee value."""

    __ctypesx_ctype__: type[Any]


class _ClassCtypesxValue(Protocol):
    """Variant for wrappers that explicitly annotate class metadata."""

    __ctypesx_ctype__: ClassVar[type[Any]]


class _IndexCtypesxValue(Protocol):
    __ctypesx_ctype__: type[Any]

    def __index__(self) -> int: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsIndex,
        /,
    ) -> object: ...


class _CharCtypesxValue(_IndexCtypesxValue, Protocol):
    @classmethod
    def _to_ctypes_value(
        cls,
        value: str | bytes | SupportsIndex,
        /,
    ) -> object: ...


class _ClassIndexCtypesxValue(Protocol):
    __ctypesx_ctype__: ClassVar[type[Any]]

    def __index__(self) -> int: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsIndex,
        /,
    ) -> object: ...


class _ClassCharCtypesxValue(_ClassIndexCtypesxValue, Protocol):
    @classmethod
    def _to_ctypes_value(
        cls,
        value: str | bytes | SupportsIndex,
        /,
    ) -> object: ...


class _WCharCtypesxValue(Protocol):
    __ctypesx_ctype__: type[Any]

    @classmethod
    def _to_ctypes_value(cls, value: str, /) -> object: ...


class _ClassWCharCtypesxValue(Protocol):
    __ctypesx_ctype__: ClassVar[type[Any]]

    @classmethod
    def _to_ctypes_value(cls, value: str, /) -> object: ...


class _FloatCtypesxValue(Protocol):
    __ctypesx_ctype__: type[Any]

    def __float__(self) -> float: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsFloat | SupportsIndex,
        /,
    ) -> object: ...


class _ClassFloatCtypesxValue(Protocol):
    __ctypesx_ctype__: ClassVar[type[Any]]

    def __float__(self) -> float: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsFloat | SupportsIndex,
        /,
    ) -> object: ...


class _ComplexCtypesxValue(Protocol):
    __ctypesx_ctype__: type[Any]

    def __complex__(self) -> complex: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsComplex | SupportsFloat | SupportsIndex,
        /,
    ) -> object: ...


class _ClassComplexCtypesxValue(Protocol):
    __ctypesx_ctype__: ClassVar[type[Any]]

    def __complex__(self) -> complex: ...

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsComplex | SupportsFloat | SupportsIndex,
        /,
    ) -> object: ...


_CtypesxPointeeT = TypeVar(
    "_CtypesxPointeeT",
    bound=_CtypesxValue | _ClassCtypesxValue,
)
_IndexPointeeT = TypeVar(
    "_IndexPointeeT",
    bound=_IndexCtypesxValue | _ClassIndexCtypesxValue,
)
_CharPointeeT = TypeVar(
    "_CharPointeeT",
    bound=_CharCtypesxValue | _ClassCharCtypesxValue,
)
_WCharPointeeT = TypeVar(
    "_WCharPointeeT",
    bound=_WCharCtypesxValue | _ClassWCharCtypesxValue,
)
_FloatPointeeT = TypeVar(
    "_FloatPointeeT",
    bound=_FloatCtypesxValue | _ClassFloatCtypesxValue,
)
_ComplexPointeeT = TypeVar(
    "_ComplexPointeeT",
    bound=_ComplexCtypesxValue | _ClassComplexCtypesxValue,
)
_StructPointeeT = TypeVar("_StructPointeeT", bound=ctypes.Structure)
_UnionPointeeT = TypeVar("_UnionPointeeT", bound=ctypes.Union)


_MISSING = object()
_POINTER_BITS = ctypes.sizeof(ctypes.c_void_p) * 8
_MAX_ADDRESS = (1 << _POINTER_BITS) - 1


def _ctype_for(type_: object, *, allow_void: bool = False) -> type[Any] | None:
    """Return the concrete ctypes storage type for a ctypesx type."""

    if type_ is None and allow_void:
        return None

    candidate = getattr(type_, "__ctypesx_ctype__", type_)
    if candidate is None and allow_void:
        return None
    if not isinstance(candidate, type):
        raise TypeError(
            f"{type_!r} does not provide a ctypes storage type through "
            "__ctypesx_ctype__"
        )
    try:
        ctypes.sizeof(candidate)
    except TypeError as error:
        raise TypeError(f"{type_!r} is not a ctypes-compatible type") from error
    return candidate


def _address(value: object, *, name: str = "pointer address") -> int:
    """Validate an integer as an unsigned native pointer bit pattern."""

    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer address, not bool")
    try:
        result = operator.index(cast(Any, value))
    except TypeError as error:
        raise TypeError(f"{name} must be an integer address") from error
    if not 0 <= result <= _MAX_ADDRESS:
        raise OverflowError(
            f"{name} {result} is outside the native pointer range "
            f"[0, {_MAX_ADDRESS}]"
        )
    return result


def _length(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("span length must be an integer, not bool")
    try:
        result = operator.index(cast(Any, value))
    except TypeError as error:
        raise TypeError("span length must be an integer") from error
    if result < 0:
        raise ValueError("span length cannot be negative")
    return result


def _to_ctypes_value(type_: object, ctype: type[Any], value: object) -> object:
    """Recursively convert one value for assignment to *ctype*."""

    converter = getattr(type_, "_to_ctypes_value", None)
    if converter is None:
        converter = getattr(type_, "_to_ctypes", None)
    if converter is not None:
        return converter(value)

    if isinstance(value, ctype):
        return value

    if ctype is ctypes.c_char:
        if isinstance(value, str):
            if len(value) != 1 or not value.isascii():
                raise ValueError("a C char requires exactly one ASCII character")
            return value.encode("ascii")
        if isinstance(value, (bytes, bytearray)):
            converted = bytes(value)
            if len(converted) != 1:
                raise ValueError("a C char requires exactly one byte")
            return converted
        integer = _address(value, name="C char value")
        if integer > 0xFF:
            raise OverflowError("C char value is outside the byte range [0, 255]")
        return bytes((integer,))

    if ctype is ctypes.c_wchar:
        if not isinstance(value, str) or len(value) != 1:
            raise ValueError("a C wchar_t requires exactly one character")
        return value

    # Simple ctypes scalars expose ``value``.  Building a temporary lets ctypes
    # perform its native conversion for users that intentionally use raw ctypes
    # element types rather than ctypesx scalar wrappers.
    try:
        converted = ctype(value)
    except (TypeError, ValueError, OverflowError):
        raise
    return getattr(converted, "value", converted)


def _from_ctypes_value(type_: object, value: object) -> object:
    converter = getattr(type_, "_from_ctypes_value", None)
    if converter is not None:
        return converter(value)
    if isinstance(type_, type) and type_ is not getattr(
        type_, "__ctypesx_ctype__", type_
    ):
        return type_(value)
    return value


def _is_sequence_input(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    )


class Pointer(Generic[_ElementT_co]):
    """A runtime factory for a typed, managed ``ctypes.POINTER(T)`` class.

    ``Pointer[T](integer)`` treats the integer as an address.  To create a
    pointer to values, pass a sequence instead: ``Pointer[U32]([7])``.
    """

    if TYPE_CHECKING:

        __ctypesx_ctype__: ClassVar[type[Any]]
        _type_: ClassVar[type[Any]]

        def __new__(cls, value: Any = None, /) -> Self: ...

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> Self: ...

        def __set__(
            self: Pointer[_Convertible[_WriteT]],
            instance: object,
            value: Pointer[_ElementT_co]
            | Sequence[_WriteT]
            | int
            | None,
            /,
        ) -> None: ...

        @classmethod
        def _coerce(cls, value: object) -> Self: ...

        @classmethod
        def _to_ctypes_assignment(
            cls, value: object
        ) -> tuple[Self, object | None]: ...

        @classmethod
        def _from_ctypes_value(
            cls, raw: object, owner: object | None = None
        ) -> Self: ...

        @property
        def address(self) -> int: ...

        @property
        def known_length(self) -> int | None: ...

        @property
        def is_null(self) -> bool: ...

        @property
        def is_const(self) -> bool: ...

        def __getitem__(self, index: int) -> _ElementT_co: ...

        def __setitem__(
            self: Pointer[_Convertible[_WriteT]],
            index: int,
            value: _WriteT,
        ) -> None: ...

        def __enter__(self) -> Self: ...

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: object | None,
        ) -> None: ...

    def __class_getitem__(cls, element_type: object) -> type[Any]:
        return _pointer_type(element_type, const=False)


class ConstPointer(Generic[_ElementT_co]):
    """The read-only-view counterpart of :class:`Pointer`."""

    if TYPE_CHECKING:

        __ctypesx_ctype__: ClassVar[type[Any]]
        _type_: ClassVar[type[Any]]

        def __new__(cls, value: Any = None, /) -> Self: ...

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> Self: ...

        def __set__(
            self: ConstPointer[_Convertible[_WriteT]],
            instance: object,
            value: ConstPointer[_ElementT_co]
            | Pointer[_ElementT_co]
            | Sequence[_WriteT]
            | int
            | None,
            /,
        ) -> None: ...

        @classmethod
        def _coerce(cls, value: object) -> Self: ...

        @classmethod
        def _to_ctypes_assignment(
            cls, value: object
        ) -> tuple[Self, object | None]: ...

        @classmethod
        def _from_ctypes_value(
            cls, raw: object, owner: object | None = None
        ) -> Self: ...

        @property
        def address(self) -> int: ...

        @property
        def known_length(self) -> int | None: ...

        @property
        def is_null(self) -> bool: ...

        @property
        def is_const(self) -> bool: ...

        def __getitem__(self, index: int) -> _ElementT_co: ...

        def __enter__(self) -> Self: ...

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: object | None,
        ) -> None: ...

    def __class_getitem__(cls, element_type: object) -> type[Any]:
        return _pointer_type(element_type, const=True)


class _ManagedPointerMixin:
    __ctypesx_pointee__: object
    __ctypesx_ctype__: type[Any]
    _ctypesx_const: bool = False
    _ctypesx_known_length: int | None
    _ctypesx_context_depth: int
    _ctypesx_context_pinned: bool
    _ctypesx_context_record: object
    _ctypesx_origin: str
    _ctypesx_owner: object
    _ctypesx_record_offset: int
    _ctypesx_record_owner: object
    _type_: type[Any]

    def __new__(cls, value: object = _MISSING) -> Self:
        if value is _MISSING:
            return super().__new__(cls)
        return cls._coerce(value)

    def __init__(self, value: object = _MISSING) -> None:
        # The pointer bits are installed by ``_coerce`` in ``__new__``.
        del value

    @classmethod
    def _from_address_bits(cls, address: int) -> Self:
        result = cast(Any, cls).from_buffer_copy(
            ctypes.c_void_p(address or None)
        )
        result._ctypesx_known_length = None
        result._ctypesx_origin = "raw"
        return cast(Self, result)

    @classmethod
    def _from_owner(cls, owner: object, *, length: int | None) -> Self:
        # ctypes.cast records ``owner`` in the result's ``_objects`` graph.
        # That graph, unlike a normal attribute, is propagated when this
        # pointer is assigned to a ctypes Structure field.
        if isinstance(owner, ctypes.Array):
            cast_source: Any = cast(Any, owner)
        else:
            cast_source = cast(Any, ctypes.pointer(cast(Any, owner)))
        result = ctypes.cast(cast_source, cast(Any, cls))
        result._ctypesx_owner = owner
        result._ctypesx_known_length = length
        result._ctypesx_origin = "owned"
        return cast(Self, result)

    def _set_address_bits(self, address: int) -> None:
        bits = ctypes.c_void_p(address or None)
        ctypes.memmove(
            ctypes.addressof(cast(Any, self)),
            ctypes.byref(bits),
            ctypes.sizeof(bits),
        )

    @classmethod
    def _from_compatible_pointer(cls, value: _ManagedPointerMixin) -> Self:
        source_type = type(value)
        if source_type.__ctypesx_pointee__ is not cls.__ctypesx_pointee__:
            raise TypeError("cannot convert a pointer with a different pointee type")
        if source_type._ctypesx_const and not cls._ctypesx_const:
            raise TypeError("cannot remove const qualification from a pointer")

        result = ctypes.cast(cast(Any, value), cast(Any, cls))
        result._ctypesx_known_length = value.known_length
        result._ctypesx_origin = getattr(value, "_ctypesx_origin", "raw")
        if hasattr(value, "_ctypesx_owner"):
            result._ctypesx_owner = value._ctypesx_owner
        if hasattr(value, "_ctypesx_record_owner"):
            result._ctypesx_record_owner = value._ctypesx_record_owner
            result._ctypesx_record_offset = value._ctypesx_record_offset
        return cast(Self, result)

    def _refresh_record_address(self) -> None:
        record = getattr(self, "_ctypesx_record_owner", None)
        if record is None:
            return
        from .records import (
            CStruct,
            CUnion,
            _record_address,  # pyright: ignore[reportPrivateUsage]
        )

        if not isinstance(record, (CStruct, CUnion)):
            raise RuntimeError("record-backed pointer lost its record owner")
        self._set_address_bits(
            _record_address(record) + self._ctypesx_record_offset
        )

    @classmethod
    def _from_sequence(cls, values: Sequence[object]) -> Self:
        element_type = cls.__ctypesx_pointee__
        ctype = cls._type_
        converted = [
            _to_ctypes_value(element_type, ctype, item) for item in values
        ]
        array_type = cast(Any, ctype) * len(converted)
        owner = array_type(*converted)
        return cls._from_owner(owner, length=len(converted))

    @classmethod
    def _from_char_string(cls, value: str | bytes | bytearray) -> Self:
        if isinstance(value, str):
            if not value.isascii():
                raise ValueError("char pointer strings must contain only ASCII")
            if "\0" in value:
                raise ValueError("char pointer strings cannot contain embedded NUL")
            encoded = value.encode("ascii")
        else:
            encoded = bytes(value)
            if b"\0" in encoded:
                raise ValueError("char pointer strings cannot contain embedded NUL")
        owner = ctypes.create_string_buffer(encoded)
        return cls._from_owner(owner, length=len(encoded) + 1)

    @classmethod
    def _from_wchar_string(cls, value: str) -> Self:
        if "\0" in value:
            raise ValueError("wchar pointer strings cannot contain embedded NUL")
        owner = ctypes.create_unicode_buffer(value)
        return cls._from_owner(owner, length=len(owner))

    @classmethod
    def _coerce(cls, value: object) -> Self:
        if isinstance(value, cls):
            return value
        if value is None:
            return cls._from_address_bits(0)
        if isinstance(value, _ManagedPointerMixin):
            return cls._from_compatible_pointer(value)

        ctype = cls._type_
        if ctype is ctypes.c_char and isinstance(
            value, (str, bytes, bytearray)
        ):
            return cls._from_char_string(value)
        if ctype is ctypes.c_wchar and isinstance(value, str):
            return cls._from_wchar_string(value)

        if _is_sequence_input(value):
            return cls._from_sequence(cast(Sequence[object], value))

        return cls._from_address_bits(_address(value))

    @classmethod
    def _to_ctypes_value(cls, value: object) -> Self:
        return cls._coerce(value)

    @classmethod
    def _to_ctypes(cls, value: object) -> Self:
        return cls._coerce(value)

    @classmethod
    def _to_ctypes_assignment(cls, value: object) -> tuple[Self, object | None]:
        """Return the field value and its optional ownership sidecar token."""

        result = cls._coerce(value)
        owner: object | None = (
            result
            if getattr(result, "_ctypesx_origin", "raw") == "owned"
            else None
        )
        record = getattr(result, "_ctypesx_record_owner", None)
        if owner is not None and record is not None:
            owner = _PinnedPointerOwner(result, record)
            result._refresh_record_address()
        return result, owner

    @classmethod
    def _from_ctypes_value(
        cls, raw: object, owner: object | None = None
    ) -> Self:
        """Rebuild a typed pointer from a ctypes field and sidecar token."""

        source_owner = (
            owner.pointer if isinstance(owner, _PinnedPointerOwner) else owner
        )
        raw_address = ctypes.cast(cast(Any, raw), ctypes.c_void_p).value or 0
        if isinstance(source_owner, cls) and source_owner.address == raw_address:
            return source_owner
        if isinstance(raw, cls):
            result = raw
        else:
            result = cls._from_address_bits(raw_address)
        if source_owner is not None:
            result._ctypesx_owner = source_owner
            result._ctypesx_known_length = getattr(
                source_owner, "known_length", None
            )
            result._ctypesx_origin = "owned"
            if hasattr(source_owner, "_ctypesx_record_owner"):
                typed_owner = cast(Any, source_owner)
                result._ctypesx_record_owner = (
                    typed_owner._ctypesx_record_owner
                )
                result._ctypesx_record_offset = (
                    typed_owner._ctypesx_record_offset
                )
        return result

    @property
    def address(self) -> int:
        return ctypes.cast(cast(Any, self), ctypes.c_void_p).value or 0

    @property
    def known_length(self) -> int | None:
        known = getattr(self, "_ctypesx_known_length", None)
        record = getattr(self, "_ctypesx_record_owner", None)
        if known is None or record is None:
            return known
        from .records import (
            CStruct,
            CUnion,
            _record_extent,  # pyright: ignore[reportPrivateUsage]
        )

        if not isinstance(record, (CStruct, CUnion)):
            raise RuntimeError("record-backed pointer lost its record owner")
        available = max(
            0,
            _record_extent(record) - self._ctypesx_record_offset,
        )
        capacity = available // ctypes.sizeof(type(self)._type_)
        return min(known, capacity)

    @property
    def is_null(self) -> bool:
        return not bool(self)

    @property
    def is_const(self) -> bool:
        return type(self)._ctypesx_const

    def __getitem__(self, index: int) -> object:
        value = cast(Any, super()).__getitem__(index)
        return _from_ctypes_value(type(self).__ctypesx_pointee__, value)

    def __setitem__(self, index: int, value: object) -> None:
        if type(self)._ctypesx_const:
            raise TypeError("cannot write through a const pointer")
        converted = _to_ctypes_value(
            type(self).__ctypesx_pointee__, type(self)._type_, value
        )
        cast(Any, super()).__setitem__(index, converted)

    def __enter__(self) -> Self:
        depth = getattr(self, "_ctypesx_context_depth", 0)
        if depth == 0:
            record = getattr(self, "_ctypesx_record_owner", None)
            from .records import (
                CStruct,
                CUnion,
                _pin_record,  # pyright: ignore[reportPrivateUsage]
                _unpin_record,  # pyright: ignore[reportPrivateUsage]
            )

            pinned = isinstance(record, (CStruct, CUnion))
            if pinned:
                _pin_record(record)
                try:
                    # Pin first, then resolve the address.  A held nested
                    # record or array may otherwise still carry the address
                    # it had before its root allocation moved.
                    self._refresh_record_address()
                except BaseException:
                    _unpin_record(record)
                    raise
                self._ctypesx_context_record = record
            self._ctypesx_context_pinned = pinned
        self._ctypesx_context_depth = depth + 1
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exception_type, exception, traceback
        depth = getattr(self, "_ctypesx_context_depth", 0)
        if depth <= 0:
            raise RuntimeError("unbalanced pointer context exit")
        depth -= 1
        self._ctypesx_context_depth = depth
        if depth == 0 and getattr(
            self,
            "_ctypesx_context_pinned",
            False,
        ):
            record = getattr(self, "_ctypesx_context_record", None)
            from .records import (
                CStruct,
                CUnion,
                _unpin_record,  # pyright: ignore[reportPrivateUsage]
            )

            if not isinstance(record, (CStruct, CUnion)):
                raise RuntimeError("pinned pointer lost its record owner")
            _unpin_record(record)
            self._ctypesx_context_pinned = False
            self._ctypesx_context_record = None


class _PinnedPointerOwner:
    """Keep a moving record pinned while an ABI pointer field exports it."""

    __slots__ = ("pointer", "record", "_active")

    def __init__(self, pointer: object, record: object) -> None:
        from .records import (
            CStruct,
            CUnion,
            _pin_record,  # pyright: ignore[reportPrivateUsage]
        )

        if not isinstance(record, (CStruct, CUnion)):
            raise TypeError("a pointer export owner must be a C record")
        _pin_record(record)
        self.pointer = pointer
        self.record = record
        self._active = True

    def __del__(self) -> None:
        if not getattr(self, "_active", False):
            return
        self._active = False
        try:
            from .records import (
                _unpin_record,  # pyright: ignore[reportPrivateUsage]
            )

            _unpin_record(cast(Any, self.record))
        except (ImportError, RuntimeError, TypeError):
            # Module teardown and partially finalized record graphs cannot be
            # made actionable from a destructor.
            pass


_pointer_cache: dict[tuple[object, bool], type[Any]] = {}


def _pointer_type(element_type: object, *, const: bool) -> type[Any]:
    key = (element_type, const)
    cached = _pointer_cache.get(key)
    if cached is not None:
        return cached

    ctype = _ctype_for(element_type)
    assert ctype is not None
    base = ctypes.POINTER(ctype)
    prefix = "ConstPointer" if const else "Pointer"
    name = f"{prefix}_{getattr(element_type, '__name__', ctype.__name__)}"
    namespace: dict[str, object] = {
        "__module__": __name__,
        "_type_": ctype,
        "__ctypesx_pointee__": element_type,
        "_ctypesx_const": const,
    }
    result = type(name, (_ManagedPointerMixin, base), namespace)
    result.__ctypesx_ctype__ = result
    _pointer_cache[key] = result
    return result


if TYPE_CHECKING:

    class CharPointer(Pointer[bytes]):
        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
        ) -> Self: ...

        def __new__(
            cls,
            value: CharPointer
            | str
            | bytes
            | bytearray
            | int
            | Sequence[str | bytes | bytearray | SupportsIndex]
            | None = None,
            /,
        ) -> Self: ...

        def __set__(  # pyright: ignore[reportIncompatibleMethodOverride]
            self,
            instance: object,
            value: CharPointer
            | str
            | bytes
            | bytearray
            | int
            | Sequence[str | bytes | bytearray | SupportsIndex]
            | None,
            /,
        ) -> None: ...


    class ConstCharPointer(ConstPointer[bytes]):
        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
        ) -> Self: ...

        def __new__(
            cls,
            value: ConstCharPointer
            | CharPointer
            | str
            | bytes
            | bytearray
            | int
            | Sequence[str | bytes | bytearray | SupportsIndex]
            | None = None,
            /,
        ) -> Self: ...

        def __set__(  # pyright: ignore[reportIncompatibleMethodOverride]
            self,
            instance: object,
            value: ConstCharPointer
            | CharPointer
            | str
            | bytes
            | bytearray
            | int
            | Sequence[str | bytes | bytearray | SupportsIndex]
            | None,
            /,
        ) -> None: ...


    class WCharPointer(Pointer[str]):
        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
        ) -> Self: ...

        def __new__(
            cls,
            value: WCharPointer | str | int | Sequence[str] | None = None,
            /,
        ) -> Self: ...

        def __set__(  # pyright: ignore[reportIncompatibleMethodOverride]
            self,
            instance: object,
            value: WCharPointer | str | int | Sequence[str] | None,
            /,
        ) -> None: ...


    class ConstWCharPointer(ConstPointer[str]):
        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
        ) -> Self: ...

        def __new__(
            cls,
            value: ConstWCharPointer
            | WCharPointer
            | str
            | int
            | Sequence[str]
            | None = None,
            /,
        ) -> Self: ...

        def __set__(  # pyright: ignore[reportIncompatibleMethodOverride]
            self,
            instance: object,
            value: ConstWCharPointer
            | WCharPointer
            | str
            | int
            | Sequence[str]
            | None,
            /,
        ) -> None: ...

else:
    CharPointer = Pointer[ctypes.c_char]
    ConstCharPointer = ConstPointer[ctypes.c_char]
    WCharPointer = Pointer[ctypes.c_wchar]
    ConstWCharPointer = ConstPointer[ctypes.c_wchar]


class VoidPointer(ctypes.c_void_p):
    """A checked ``void *`` value.

    Integer inputs are addresses, never pointee values.  As with raw ctypes,
    ctypesx cannot establish whether a non-null address is valid.
    """

    __ctypesx_ctype__: ClassVar[type[VoidPointer]]
    _ctypesx_context_depth: int
    _ctypesx_context_pinned: bool
    _ctypesx_owner: object
    _ctypesx_record_offset: int
    _ctypesx_record_owner: object

    if TYPE_CHECKING:

        @overload
        def __new__(
            cls,
            value: VoidPointer | int | None = None,
            /,
        ) -> Self: ...

        @overload
        def __new__(
            cls,
            value: (
                Pointer[Any]
                | ConstPointer[Any]
                | Span[Any]
                | ConstSpan[Any]
            ),
            /,
        ) -> Self: ...

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: (
                VoidPointer
                | int
                | None
                | Pointer[Any]
                | ConstPointer[Any]
                | Span[Any]
                | ConstSpan[Any]
            ),
            /,
        ) -> None: ...

        def __enter__(self) -> Self: ...

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: object | None,
        ) -> None: ...

    def __new__(cls, value: object = _MISSING) -> Self:
        if value is _MISSING or value is None:
            return cast(Self, cls.from_buffer_copy(ctypes.c_void_p()))
        if isinstance(value, cls):
            return value
        if isinstance(value, _SpanBase):
            value = cast(Any, value).pointer
        if isinstance(value, _ManagedPointerMixin):
            result = ctypes.cast(cast(Any, value), cls)
            result._ctypesx_owner = value
            if hasattr(value, "_ctypesx_record_owner"):
                typed_value = cast(Any, value)
                result._ctypesx_record_owner = typed_value._ctypesx_record_owner
                result._ctypesx_record_offset = typed_value._ctypesx_record_offset
            return result
        address = _address(value, name="void pointer address")
        return cast(Self, cls.from_buffer_copy(ctypes.c_void_p(address or None)))

    def __init__(self, value: object = _MISSING) -> None:
        del value

    @classmethod
    def _coerce(cls, value: object) -> Self:
        return cast(Any, cls)(value)

    @classmethod
    def _to_ctypes_value(cls, value: object) -> Self:
        return cast(Any, cls)(value)

    @classmethod
    def _to_ctypes(cls, value: object) -> Self:
        return cast(Any, cls)(value)

    @classmethod
    def _to_ctypes_assignment(cls, value: object) -> tuple[Self, object | None]:
        result = cast(Any, cls)(value)
        owner: object | None = (
            result
            if getattr(result, "_objects", None)
            or hasattr(result, "_ctypesx_owner")
            else None
        )
        record = getattr(result, "_ctypesx_record_owner", None)
        if owner is not None and record is not None:
            owner = _PinnedPointerOwner(result, record)
            result._refresh_record_address()
        return result, owner

    @classmethod
    def _from_ctypes_value(
        cls, raw: object, owner: object | None = None
    ) -> Self:
        source_owner = (
            owner.pointer if isinstance(owner, _PinnedPointerOwner) else owner
        )
        converted = cast(Any, cls)(raw)
        if (
            isinstance(source_owner, cls)
            and source_owner.address == converted.address
        ):
            return source_owner
        result = converted
        if source_owner is not None:
            result._ctypesx_owner = source_owner
            if hasattr(source_owner, "_ctypesx_record_owner"):
                typed_owner = cast(Any, source_owner)
                result._ctypesx_record_owner = (
                    typed_owner._ctypesx_record_owner
                )
                result._ctypesx_record_offset = (
                    typed_owner._ctypesx_record_offset
                )
        return result

    def _raw_address(self) -> int:
        return self.value or 0

    def _set_address_bits(self, address: int) -> None:
        bits = ctypes.c_void_p(address or None)
        ctypes.memmove(
            ctypes.addressof(self),
            ctypes.byref(bits),
            ctypes.sizeof(bits),
        )

    def _refresh_record_address(self) -> None:
        record = getattr(self, "_ctypesx_record_owner", None)
        if record is None:
            return
        from .records import (
            CStruct,
            CUnion,
            _record_address,  # pyright: ignore[reportPrivateUsage]
        )

        if not isinstance(record, (CStruct, CUnion)):
            raise RuntimeError("record-backed void pointer lost its owner")
        self._set_address_bits(
            _record_address(record) + self._ctypesx_record_offset
        )

    @property
    def address(self) -> int:
        with self:
            return self._raw_address()

    @property
    def is_null(self) -> bool:
        return self.address == 0

    def __enter__(self) -> Self:
        depth = getattr(self, "_ctypesx_context_depth", 0)
        if depth == 0:
            record = getattr(self, "_ctypesx_record_owner", None)
            from .records import (
                CStruct,
                CUnion,
                _pin_record,  # pyright: ignore[reportPrivateUsage]
                _unpin_record,  # pyright: ignore[reportPrivateUsage]
            )

            pinned = isinstance(record, (CStruct, CUnion))
            if pinned:
                _pin_record(record)
                try:
                    self._refresh_record_address()
                except BaseException:
                    _unpin_record(record)
                    raise
            self._ctypesx_context_pinned = pinned
        self._ctypesx_context_depth = depth + 1
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exception_type, exception, traceback
        depth = getattr(self, "_ctypesx_context_depth", 0)
        if depth <= 0:
            raise RuntimeError("unbalanced void pointer context exit")
        depth -= 1
        self._ctypesx_context_depth = depth
        if depth == 0 and getattr(self, "_ctypesx_context_pinned", False):
            record = getattr(self, "_ctypesx_record_owner", None)
            from .records import (
                CStruct,
                CUnion,
                _unpin_record,  # pyright: ignore[reportPrivateUsage]
            )

            if not isinstance(record, (CStruct, CUnion)):
                raise RuntimeError("pinned void pointer lost its owner")
            _unpin_record(record)
            self._ctypesx_context_pinned = False


VoidPointer.__ctypesx_ctype__ = VoidPointer


class FunctionPointer(Generic[_Params, _ResultT_co]):
    """A runtime factory for native C callback pointer types."""

    if TYPE_CHECKING:

        __ctypesx_ctype__: ClassVar[type[Any]]

        def __new__(cls, value: Any = None, /) -> Self: ...

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: int
            | None
            | FunctionPointer[_Params, _ResultT_co]
            | Callable[_Params, _ResultT_co],
            /,
        ) -> None: ...

        @classmethod
        def _coerce(cls, value: object) -> Self: ...

        @classmethod
        def _to_ctypes_assignment(
            cls, value: object
        ) -> tuple[Self, object | None]: ...

        @classmethod
        def _from_ctypes_value(
            cls, raw: object, owner: object | None = None
        ) -> Self: ...

        @property
        def address(self) -> int: ...

        @property
        def is_null(self) -> bool: ...

        def __call__(
            self, *args: _Params.args, **kwargs: _Params.kwargs
        ) -> _ResultT_co: ...

    def __class_getitem__(cls, signature: object) -> type[Any]:
        if not isinstance(signature, tuple):
            raise TypeError(
                "FunctionPointer requires FunctionPointer[[Arg1, ...], Result]"
            )
        checked_signature = cast(tuple[object, ...], signature)
        if len(checked_signature) != 2:
            raise TypeError(
                "FunctionPointer requires FunctionPointer[[Arg1, ...], Result]"
            )
        argument_types, result_type = checked_signature
        if not isinstance(argument_types, (list, tuple)):
            raise TypeError("function pointer argument types must be a list or tuple")
        return _function_pointer_type(
            tuple(cast(Sequence[object], argument_types)), result_type
        )


def _coerce_callback_pointer_result(
    declared_type: object,
    ctype: type[Any],
    value: object,
) -> tuple[int | None, object]:
    """Lower a Python callback result to an owned native pointer address."""

    converter = getattr(declared_type, "_to_ctypes_value", None)
    if callable(converter):
        converted = converter(value)
    elif ctype is ctypes.c_char_p:
        if isinstance(value, bytearray):
            value = bytes(value)
        converted = (
            value
            if isinstance(value, ctype)
            else cast(Any, ctype)(value)
        )
    elif ctype is ctypes.c_wchar_p:
        converted = (
            value
            if isinstance(value, ctype)
            else cast(Any, ctype)(value)
        )
    elif isinstance(value, ctype):
        converted = value
    elif value is None:
        converted = ctype()
    elif isinstance(value, int):
        converted = ctypes.cast(
            ctypes.c_void_p(_address(value, name="callback pointer result")),
            ctype,
        )
    else:
        converted = ctype(value)

    if isinstance(converted, int):
        converted = ctypes.c_void_p(
            _address(converted, name="callback pointer result") or None
        )
    retained: object = converted
    record = getattr(converted, "_ctypesx_record_owner", None)
    if record is not None:
        retained = _PinnedPointerOwner(converted, record)
        refresh = getattr(converted, "_refresh_record_address", None)
        if not callable(refresh):
            raise RuntimeError("record-backed callback pointer cannot refresh")
        refresh()
    address = ctypes.cast(cast(Any, converted), ctypes.c_void_p).value
    return address, retained


def _restore_callback_pointer_result(
    declared_type: object,
    ctype: type[Any],
    raw: object,
    owner: object | None,
) -> object:
    """Restore a lowered pointer result to its declared public semantics."""

    from_ctypes = getattr(declared_type, "_from_ctypes_value", None)
    if callable(from_ctypes):
        if owner is not None:
            return from_ctypes(raw, owner)
        return from_ctypes(raw)

    address = ctypes.cast(cast(Any, raw), ctypes.c_void_p).value
    if ctype is ctypes.c_char_p:
        return ctypes.cast(ctypes.c_void_p(address), ctypes.c_char_p).value
    if ctype is ctypes.c_wchar_p:
        return ctypes.cast(ctypes.c_void_p(address), ctypes.c_wchar_p).value
    if ctype is ctypes.c_void_p:
        return address
    if isinstance(owner, ctype):
        owner_address = ctypes.cast(cast(Any, owner), ctypes.c_void_p).value
        if owner_address == address:
            return owner
    return ctypes.cast(ctypes.c_void_p(address), ctype)


class _ManagedFunctionPointerMixin:
    __ctypesx_ctype__: type[Any]
    __ctypesx_argument_types__: tuple[object, ...]
    __ctypesx_argument_ctypes__: tuple[type[Any], ...]
    __ctypesx_result_type__: object
    __ctypesx_result_ctype__: type[Any] | None
    __ctypesx_callback_result_ctype__: type[Any] | None
    __ctypesx_pointer_result__: bool
    _ctypesx_callback_base: type[Any]
    _ctypesx_callback: object
    _ctypesx_return_owners: list[object]

    def __new__(cls, value: object = _MISSING) -> Self:
        if value is _MISSING:
            return super().__new__(cls)
        return cls._coerce(value)

    def __init__(self, value: object = _MISSING) -> None:
        del value

    @classmethod
    def _coerce(cls, value: object) -> Self:
        if isinstance(value, cls):
            return value
        if value is None:
            return cast(
                Self,
                cast(Any, cls).from_buffer_copy(ctypes.c_void_p()),
            )
        if callable(value):
            python_callback = value
            return_owners: list[object] = []

            def adapter(*raw_arguments: object) -> object:
                python_arguments = tuple(
                    _from_ctypes_value(declared, raw)
                    for declared, raw in zip(
                        cls.__ctypesx_argument_types__,
                        raw_arguments,
                        strict=True,
                    )
                )
                python_result = python_callback(*python_arguments)
                result_ctype = cls.__ctypesx_result_ctype__
                if result_ctype is None:
                    return None
                if cls.__ctypesx_pointer_result__:
                    address, retained = _coerce_callback_pointer_result(
                        cls.__ctypesx_result_type__,
                        result_ctype,
                        python_result,
                    )
                    return_owners.append(retained)
                    return address
                return _to_ctypes_value(
                    cls.__ctypesx_result_type__,
                    result_ctype,
                    python_result,
                )

            callback = cls._ctypesx_callback_base(adapter)
            result = ctypes.cast(callback, cast(Any, cls))
            result._ctypesx_callback = callback
            result._ctypesx_return_owners = return_owners
            return cast(Self, result)
        address = _address(value, name="function pointer address")
        return cast(
            Self,
            cast(Any, cls).from_buffer_copy(
                ctypes.c_void_p(address or None)
            ),
        )

    @classmethod
    def _to_ctypes_value(cls, value: object) -> Self:
        return cls._coerce(value)

    @classmethod
    def _to_ctypes(cls, value: object) -> Self:
        return cls._coerce(value)

    @classmethod
    def _to_ctypes_assignment(cls, value: object) -> tuple[Self, object | None]:
        result = cls._coerce(value)
        owner = result if getattr(result, "_ctypesx_callback", None) else None
        return result, owner

    @classmethod
    def _from_ctypes_value(
        cls, raw: object, owner: object | None = None
    ) -> Self:
        raw_address = ctypes.cast(cast(Any, raw), ctypes.c_void_p).value or 0
        if isinstance(owner, cls) and owner.address == raw_address:
            return owner
        if isinstance(raw, cls):
            result = raw
        else:
            result = cast(Any, cls).from_buffer_copy(
                ctypes.c_void_p(raw_address or None)
            )
        if owner is not None:
            result._ctypesx_callback = owner
        return result

    @property
    def address(self) -> int:
        return ctypes.cast(cast(Any, self), ctypes.c_void_p).value or 0

    @property
    def is_null(self) -> bool:
        return not bool(self)

    def __call__(self, *arguments: object, **keywords: object) -> object:
        if keywords:
            raise TypeError("C function pointers do not accept keyword arguments")
        expected = len(type(self).__ctypesx_argument_types__)
        if len(arguments) != expected:
            raise TypeError(
                f"function pointer takes {expected} arguments "
                f"but {len(arguments)} were given"
            )
        converted = tuple(
            _to_ctypes_value(declared, ctype, value)
            for declared, ctype, value in zip(
                type(self).__ctypesx_argument_types__,
                type(self).__ctypesx_argument_ctypes__,
                arguments,
                strict=True,
            )
        )
        raw_result = cast(Any, super()).__call__(*converted)
        if type(self).__ctypesx_result_ctype__ is None:
            return None
        result_type = type(self).__ctypesx_result_type__
        if type(self).__ctypesx_pointer_result__:
            owners = getattr(self, "_ctypesx_return_owners", [])
            owner = owners[-1] if owners else None
            return _restore_callback_pointer_result(
                result_type,
                cast(type[Any], type(self).__ctypesx_result_ctype__),
                raw_result,
                owner,
            )
        return _from_ctypes_value(
            result_type,
            raw_result,
        )


_function_pointer_cache: dict[
    tuple[tuple[object, ...], object], type[Any]
] = {}


_CALLBACK_POINTER_BASES: tuple[type[Any], ...] = (
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_wchar_p,
    cast(type[Any], getattr(ctypes, "_Pointer")),
    cast(type[Any], getattr(ctypes, "_CFuncPtr")),
)


def _is_callback_pointer_ctype(ctype: type[Any] | None) -> bool:
    return ctype is not None and issubclass(ctype, _CALLBACK_POINTER_BASES)


def _function_pointer_type(
    argument_types: tuple[object, ...], result_type: object
) -> type[Any]:
    key = (argument_types, result_type)
    cached = _function_pointer_cache.get(key)
    if cached is not None:
        return cached

    ctypes_arguments = tuple(
        cast(type[Any], _ctype_for(item)) for item in argument_types
    )
    ctypes_result = _ctype_for(result_type, allow_void=True)
    pointer_result = _is_callback_pointer_ctype(ctypes_result)
    callback_result = ctypes.c_void_p if pointer_result else ctypes_result
    callback_base = ctypes.CFUNCTYPE(callback_result, *ctypes_arguments)
    argument_names = ",".join(
        getattr(item, "__name__", repr(item)) for item in argument_types
    )
    result_name = getattr(result_type, "__name__", repr(result_type))
    name = f"FunctionPointer_({argument_names})_{result_name}"
    namespace: dict[str, object] = {
        "__module__": __name__,
        "_flags_": callback_base._flags_,
        "_argtypes_": callback_base._argtypes_,
        "_restype_": callback_base._restype_,
        "_ctypesx_callback_base": callback_base,
        "__ctypesx_argument_types__": argument_types,
        "__ctypesx_argument_ctypes__": ctypes_arguments,
        "__ctypesx_result_type__": result_type,
        "__ctypesx_result_ctype__": ctypes_result,
        "__ctypesx_callback_result_ctype__": callback_result,
        "__ctypesx_pointer_result__": pointer_result,
    }
    result = type(
        name,
        (_ManagedFunctionPointerMixin, callback_base),
        namespace,
    )
    result.__ctypesx_ctype__ = result
    _function_pointer_cache[key] = result
    return result


class _SpanBase(Generic[_ElementT_co]):
    """A bounded, non-ABI view over a typed pointer.

    A Span stores a pointer and a Python-side element count.  It is not itself
    a C structure and therefore deliberately has no ``__ctypesx_ctype__``.
    """

    _ctypesx_element_type: object | None = None
    _ctypesx_readonly = False
    _span_cache: dict[tuple[type[Any], object], type[Any]] = {}
    _ctypesx_owner: object
    _pointer: Any
    _length: int

    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            source: Sequence[object],
            length: None = None,
            /,
        ) -> None: ...

        @overload
        def __init__(
            self,
            source: Pointer[_ElementT_co],
            length: int | None = None,
            /,
        ) -> None: ...

        @overload
        def __init__(
            self,
            source: int | None,
            length: int,
            /,
        ) -> None: ...

    def __class_getitem__(cls, element_type: object) -> type[Any]:
        if isinstance(element_type, TypeVar):
            return cast(
                type[Any],
                cast(Any, super()).__class_getitem__(element_type),
            )
        if cls._ctypesx_element_type is not None:
            raise TypeError(f"{cls.__name__} is already parameterized")
        key = (cls, element_type)
        cached = cls._span_cache.get(key)
        if cached is not None:
            return cached
        _ctype_for(element_type)
        name = f"{cls.__name__}_{getattr(element_type, '__name__', repr(element_type))}"
        result = type(
            name,
            (cls,),
            {
                "__module__": __name__,
                "_ctypesx_element_type": element_type,
            },
        )
        cls._span_cache[key] = result
        return result

    def __init__(
        self,
        source: object,
        length: object = None,
        /,
    ) -> None:
        element_type = type(self)._ctypesx_element_type
        if element_type is None:
            raise TypeError("Span must be parameterized, for example Span[U8]")
        pointer_type = _pointer_type(element_type, const=False)
        const_pointer_type = _pointer_type(element_type, const=True)

        if isinstance(source, _SpanBase):
            if not type(self)._ctypesx_readonly:
                raise TypeError(
                    "construct a mutable Span from source.pointer instead"
                )
            source_span = cast(Any, source)
            if source_span._ctypesx_element_type is not element_type:
                raise TypeError("cannot construct a Span from another element type")
            pointer = source_span.pointer
            inferred_length = cast(int, source_span.__len__())
            self._ctypesx_owner = source
        elif isinstance(source, (pointer_type, const_pointer_type)):
            pointer = cast(Any, source)
            inferred_length = pointer.known_length
            self._ctypesx_owner = source
        elif _is_sequence_input(source):
            pointer = pointer_type._from_sequence(cast(Sequence[object], source))
            inferred_length = pointer.known_length
            self._ctypesx_owner = pointer
        else:
            pointer = pointer_type._coerce(source)
            inferred_length = pointer.known_length
            self._ctypesx_owner = pointer

        if pointer.is_const and not type(self)._ctypesx_readonly:
            raise TypeError(
                "a mutable Span cannot use a ConstPointer; use ConstSpan"
            )

        if length is None:
            if inferred_length is None:
                raise TypeError("a raw pointer requires an explicit Span length")
            final_length = inferred_length
        else:
            final_length = _length(length)
            if inferred_length is not None and final_length > inferred_length:
                raise ValueError(
                    "Span length exceeds the known size of its backing buffer"
                )
        if final_length and not bool(pointer):
            raise ValueError("a non-empty Span cannot use a null pointer")

        self._pointer = pointer
        self._length = final_length

    @property
    def pointer(
        self,
    ) -> Pointer[_ElementT_co] | ConstPointer[_ElementT_co]:
        pointer = self._pointer
        with pointer:
            return pointer

    def _validate_backing_length(self) -> None:
        known_length = self._pointer.known_length
        if known_length is not None and self._length > known_length:
            raise BufferError(
                "Span backing storage is now shorter than the Span"
            )

    @property
    def address(self) -> int:
        with self._pointer:
            self._validate_backing_length()
            return cast(int, self._pointer.address)

    @property
    def is_const(self) -> bool:
        return cast(bool, self._pointer.is_const)

    def __len__(self) -> int:
        with self._pointer:
            self._validate_backing_length()
        return self._length

    @overload
    def __getitem__(self, index: int) -> _ElementT_co: ...

    @overload
    def __getitem__(self, index: slice) -> list[_ElementT_co]: ...

    def __getitem__(
        self, index: int | slice
    ) -> _ElementT_co | list[_ElementT_co]:
        with self._pointer:
            self._validate_backing_length()
            if isinstance(index, slice):
                return [
                    cast(_ElementT_co, self._pointer[position])
                    for position in range(*index.indices(self._length))
                ]
            normalized = operator.index(index)
            if normalized < 0:
                normalized += self._length
            if not 0 <= normalized < self._length:
                raise IndexError("Span index out of range")
            return cast(_ElementT_co, self._pointer[normalized])

    @overload
    def __setitem__(
        self: Span[_Convertible[_WriteT]],
        index: int,
        value: _WriteT,
    ) -> None: ...

    @overload
    def __setitem__(
        self: Span[_Convertible[_WriteT]],
        index: slice,
        value: Sequence[_WriteT],
    ) -> None: ...

    def __setitem__(
        self, index: int | slice, value: object | Sequence[object]
    ) -> None:
        with self._pointer:
            self._validate_backing_length()
            if self._pointer.is_const:
                raise TypeError("cannot write through a const Span")
            if isinstance(index, slice):
                if not _is_sequence_input(value):
                    raise TypeError("Span slice assignment requires a sequence")
                positions = list(range(*index.indices(self._length)))
                values = list(cast(Sequence[object], value))
                if len(positions) != len(values):
                    raise ValueError(
                        "Span slice assignment cannot change its length"
                    )
                pointer_type = cast(
                    type[_ManagedPointerMixin],
                    type(self._pointer),
                )
                converted = [
                    _to_ctypes_value(
                        pointer_type.__ctypesx_pointee__,
                        pointer_type._type_,  # pyright: ignore[reportPrivateUsage]
                        item,
                    )
                    for item in values
                ]
                for position, item in zip(
                    positions,
                    converted,
                    strict=True,
                ):
                    self._pointer[position] = item
                return
            normalized = operator.index(index)
            if normalized < 0:
                normalized += self._length
            if not 0 <= normalized < self._length:
                raise IndexError("Span index out of range")
            self._pointer[normalized] = value

    def __iter__(self) -> Iterator[_ElementT_co]:
        with self._pointer:
            self._validate_backing_length()
            for index in range(self._length):
                yield cast(_ElementT_co, self._pointer[index])

    def to_list(self) -> list[_ElementT_co]:
        return list(self)


class Span(_SpanBase[_ElementT_co], Generic[_ElementT_co]):
    """A bounded mutable view over typed contiguous storage."""

    _ctypesx_readonly = False


class ConstSpan(_SpanBase[_ElementT_co], Generic[_ElementT_co]):
    """A bounded read-only view over mutable or const pointer storage."""

    _ctypesx_readonly = True

    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            source: Sequence[object],
            length: None = None,
            /,
        ) -> None: ...

        @overload
        def __init__(
            self,
            source: (
                Span[_ElementT_co]
                | ConstSpan[_ElementT_co]
                | Pointer[_ElementT_co]
                | ConstPointer[_ElementT_co]
            ),
            length: int | None = None,
            /,
        ) -> None: ...

        @overload
        def __init__(
            self,
            source: int | None,
            length: int,
            /,
        ) -> None: ...

    def __init__(self, source: object, length: object = None, /) -> None:
        cast(Any, super()).__init__(source, length)
        element_type = type(self)._ctypesx_element_type
        assert element_type is not None
        const_pointer_type = _pointer_type(element_type, const=True)
        self._pointer = const_pointer_type._coerce(self._pointer)

    @property
    def pointer(self) -> ConstPointer[_ElementT_co]:
        return cast(Any, super().pointer)

    def __setitem__(
        self,
        index: int | slice,
        value: Never,
    ) -> Never:
        del index, value
        raise TypeError("cannot write through a ConstSpan")


@overload
def pointer_to(
    value: ctypes.Array[Any],
    pointee: None = None,
) -> Pointer[Any]: ...


@overload
def pointer_to(
    value: _CharPointeeT,
    pointee: None = None,
) -> Pointer[_CharPointeeT]: ...


@overload
def pointer_to(
    value: _WCharPointeeT,
    pointee: None = None,
) -> Pointer[_WCharPointeeT]: ...


@overload
def pointer_to(
    value: _ComplexPointeeT,
    pointee: None = None,
) -> Pointer[_ComplexPointeeT]: ...


@overload
def pointer_to(
    value: _FloatPointeeT,
    pointee: None = None,
) -> Pointer[_FloatPointeeT]: ...


@overload
def pointer_to(
    value: _IndexPointeeT,
    pointee: None = None,
) -> Pointer[_IndexPointeeT]: ...


@overload
def pointer_to(
    value: _CtypesxPointeeT,
    pointee: None = None,
) -> Pointer[_CtypesxPointeeT]: ...


@overload
def pointer_to(
    value: _StructPointeeT,
    pointee: None = None,
) -> Pointer[_StructPointeeT]: ...


@overload
def pointer_to(
    value: _UnionPointeeT,
    pointee: None = None,
) -> Pointer[_UnionPointeeT]: ...


@overload
def pointer_to(
    value: str | bytes | SupportsIndex,
    pointee: type[_CharPointeeT],
) -> Pointer[_CharPointeeT]: ...


@overload
def pointer_to(
    value: str,
    pointee: type[_WCharPointeeT],
) -> Pointer[_WCharPointeeT]: ...


@overload
def pointer_to(
    value: SupportsComplex | SupportsFloat | SupportsIndex,
    pointee: type[_ComplexPointeeT],
) -> Pointer[_ComplexPointeeT]: ...


@overload
def pointer_to(
    value: SupportsFloat | SupportsIndex,
    pointee: type[_FloatPointeeT],
) -> Pointer[_FloatPointeeT]: ...


@overload
def pointer_to(
    value: SupportsIndex,
    pointee: type[_IndexPointeeT],
) -> Pointer[_IndexPointeeT]: ...


@overload
def pointer_to(
    value: _CtypesxPointeeT,
    pointee: type[_CtypesxPointeeT],
) -> Pointer[_CtypesxPointeeT]: ...


@overload
def pointer_to(
    value: _StructPointeeT,
    pointee: type[_StructPointeeT],
) -> Pointer[_StructPointeeT]: ...


@overload
def pointer_to(
    value: _UnionPointeeT,
    pointee: type[_UnionPointeeT],
) -> Pointer[_UnionPointeeT]: ...


def pointer_to(value: object, pointee: object | None = None) -> Any:
    """Return an owned typed pointer to one existing or converted C value.

    A plain Python scalar needs an explicit ``pointee`` type because an integer
    passed directly to :class:`Pointer` always means an address.  A ctypesx
    scalar or record advertises its own storage type and can be inferred.

    The returned pointer is also a context manager, so both
    ``pointer_to(value)`` and ``with pointer_to(value) as pointer`` are valid.
    """

    inferred_array = False
    if pointee is None:
        value_type = type(value)
        if hasattr(value_type, "__ctypesx_ctype__"):
            pointee = value_type
        elif isinstance(value, ctypes.Array):
            pointee = cast(object, cast(Any, value)._type_)
            inferred_array = True
        else:
            try:
                ctypes.sizeof(cast(Any, value_type))
            except TypeError as error:
                raise TypeError(
                    "pointer_to needs an explicit pointee type for plain "
                    "Python values"
                ) from error
            pointee = value_type

    resolved_pointee = cast(object, pointee)
    ctype = _ctype_for(resolved_pointee)
    assert ctype is not None
    pointer_type = _pointer_type(resolved_pointee, const=False)
    exposed: object
    if inferred_array:
        result = pointer_type._from_owner(
            value,
            length=len(cast(Any, value)),
        )
        exposed = cast(object, value)
    elif isinstance(value, ctype):
        owner: object = cast(object, value)
        result = pointer_type._from_owner(owner, length=1)
        exposed = cast(object, value)
    else:
        converted = _to_ctypes_value(
            resolved_pointee, ctype, cast(object, value)
        )
        owner = ctype(converted)
        result = pointer_type._from_owner(owner, length=1)
        exposed = owner

    # A record or a ctypes array view may be backed by a parent allocation
    # whose address can move.  Save a logical record-relative offset;
    # __enter__ pins first and then resolves the live address.
    from .records import (
        CStruct,
        CUnion,
        _record_address,  # pyright: ignore[reportPrivateUsage]
    )

    current: object | None = exposed
    seen: set[int] = set()
    record: CStruct | CUnion | None = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (CStruct, CUnion)):
            record = current
            break
        next_owner = getattr(current, "_ctypesx_owner", None)
        if next_owner is None:
            next_owner = getattr(current, "_b_base_", None)
        current = next_owner

    if record is not None:
        if isinstance(exposed, (CStruct, CUnion)):
            exposed_address = _record_address(exposed)
        else:
            exposed_address = ctypes.addressof(cast(Any, exposed))
        record_address = _record_address(record)
        offset = exposed_address - record_address
        if offset < 0:
            raise RuntimeError("record-backed pointer has an invalid offset")
        result._ctypesx_record_owner = record
        result._ctypesx_record_offset = offset
        result._set_address_bits(record_address + offset)
    return result
