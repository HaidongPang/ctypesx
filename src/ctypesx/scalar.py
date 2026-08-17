"""Strict Python values for host-native C scalar types.

The classes in this module deliberately are *not* subclasses of ctypes'
``_SimpleCData`` classes.  They are ordinary, precisely typed Python values
which carry the ctypes layout type in :attr:`__ctypesx_ctype__`.  This keeps
normal Python arithmetic and comparisons unsurprising while allowing the
record compiler to build an exact native layout.

Integer construction never truncates.  Values outside the destination C
type's range raise :class:`OverflowError`; accidental non-integers and
``bool`` raise :class:`TypeError`.  C's truncating conversions remain possible
only through the explicitly named :meth:`CInteger.wrap` operation.
"""

from __future__ import annotations

import ctypes
import math
from operator import index
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Self,
    SupportsComplex,
    SupportsFloat,
    SupportsIndex,
    cast,
)


if TYPE_CHECKING:
    type _CtypesScalarType = type[
        ctypes._SimpleCData[Any]  # pyright: ignore[reportPrivateUsage]
    ]
else:
    # The private ctypes base is useful to static checkers but must not become
    # a runtime compatibility dependency of the package.
    type _CtypesScalarType = type[object]

_REPRESENTATION_ATTRIBUTES = frozenset(
    {"BITS", "SIGNED", "__ctypesx_ctype__"}
)


def _strict_index(value: SupportsIndex, /) -> int:
    """Return an integer input without treating ``bool`` as a C integer."""

    if isinstance(value, bool):
        raise TypeError("bool is not an ordinary C integer value")
    try:
        return index(value)
    except TypeError:
        raise TypeError(
            f"expected an integer, got {type(value).__name__}"
        ) from None


def _bool_index(value: bool | SupportsIndex, /) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        number = index(value)
    except TypeError:
        raise TypeError(
            f"expected bool or integer 0/1, got {type(value).__name__}"
        ) from None
    if number not in (0, 1):
        raise ValueError(f"{number} is not a C boolean value (expected 0 or 1)")
    return number


class _CScalarMeta(type):
    """Keep C representation metadata stable after class creation."""

    def __setattr__(cls, name: str, value: object, /) -> None:
        if name in _REPRESENTATION_ATTRIBUTES:
            raise TypeError(
                f"{cls.__name__}.{name} is immutable C representation metadata"
            )
        super().__setattr__(name, value)

    def __delattr__(cls, name: str, /) -> None:
        if name in _REPRESENTATION_ATTRIBUTES:
            raise TypeError(
                f"{cls.__name__}.{name} is immutable C representation metadata"
            )
        super().__delattr__(name)


class _CIntegerMeta(_CScalarMeta):
    pass


_SIGNED_INTEGER_CTYPES = (
    ctypes.c_byte,
    ctypes.c_short,
    ctypes.c_int,
    ctypes.c_long,
    ctypes.c_longlong,
    ctypes.c_ssize_t,
    ctypes.c_int8,
    ctypes.c_int16,
    ctypes.c_int32,
    ctypes.c_int64,
)

_UNSIGNED_INTEGER_CTYPES = (
    ctypes.c_ubyte,
    ctypes.c_ushort,
    ctypes.c_uint,
    ctypes.c_ulong,
    ctypes.c_ulonglong,
    ctypes.c_size_t,
    ctypes.c_uint8,
    ctypes.c_uint16,
    ctypes.c_uint32,
    ctypes.c_uint64,
)


def _integer_ctype_signedness(ctype: object, /) -> bool:
    """Return an integer ctypes type's signedness, rejecting other ctypes."""

    if not isinstance(ctype, type):
        raise TypeError("__ctypesx_ctype__ must be a ctypes integer type")
    if any(issubclass(ctype, candidate) for candidate in _SIGNED_INTEGER_CTYPES):
        return True
    if any(
        issubclass(ctype, candidate)
        for candidate in _UNSIGNED_INTEGER_CTYPES
    ):
        return False
    raise TypeError(
        f"{getattr(ctype, '__name__', ctype)!s} is not a ctypes integer type"
    )


class CInteger(int, metaclass=_CIntegerMeta):
    """Base class for a checked integer with a native ctypes layout."""

    BITS: ClassVar[int]
    SIGNED: ClassVar[bool]
    __ctypesx_ctype__: ClassVar[_CtypesScalarType]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        try:
            ctype = cls.__ctypesx_ctype__
            signed = cls.SIGNED
        except AttributeError:
            raise TypeError(
                f"{cls.__name__} must define __ctypesx_ctype__ and SIGNED"
            ) from None

        actual_signedness = _integer_ctype_signedness(ctype)
        signed_object = cast(object, signed)
        if type(signed_object) is not bool:
            raise TypeError(f"{cls.__name__}.SIGNED must be bool")
        if signed is not actual_signedness:
            raise TypeError(
                f"{cls.__name__}.SIGNED={signed} disagrees with "
                f"{ctype.__name__} signedness"
            )

        bits = ctypes.sizeof(ctype) * 8
        declared_bits = vars(cls).get("BITS")
        if declared_bits is not None and declared_bits != bits:
            raise TypeError(
                f"{cls.__name__}.BITS={declared_bits} disagrees with "
                f"sizeof({ctype.__name__})={bits} bits"
            )
        if declared_bits is None:
            type.__setattr__(cls, "BITS", bits)

        parent = next(
            (
                base
                for base in cls.__mro__[1:]
                if isinstance(base, _CIntegerMeta) and base is not CInteger
            ),
            None,
        )
        if parent is not None:
            for name in _REPRESENTATION_ATTRIBUTES:
                if name in vars(cls) and getattr(cls, name) != getattr(parent, name):
                    raise TypeError(
                        f"semantic subclass {cls.__name__} cannot change {name}"
                    )

    def __new__(cls, value: SupportsIndex = 0, /) -> Self:
        if cls is CInteger:
            raise TypeError("CInteger is an abstract scalar type")
        number = _strict_index(value)
        minimum, maximum = cls.bounds()
        if not minimum <= number <= maximum:
            raise OverflowError(
                f"{number} is outside {cls.__name__} range "
                f"[{minimum}, {maximum}]"
            )
        return int.__new__(cls, number)

    @classmethod
    def bounds(cls) -> tuple[int, int]:
        """Return the inclusive numeric range represented by ``cls``."""

        if cls.SIGNED:
            limit = 1 << (cls.BITS - 1)
            return -limit, limit - 1
        return 0, (1 << cls.BITS) - 1

    @classmethod
    def from_bits(cls, value: SupportsIndex, /) -> Self:
        """Interpret an in-range unsigned bit pattern as ``cls``."""

        bits = _strict_index(value)
        modulus = 1 << cls.BITS
        if not 0 <= bits < modulus:
            raise OverflowError(
                f"{bits} is not a {cls.BITS}-bit unsigned bit pattern"
            )
        if cls.SIGNED and bits >= modulus >> 1:
            bits -= modulus
        return cls(bits)

    @classmethod
    def wrap(cls, value: SupportsIndex, /) -> Self:
        """Explicitly truncate ``value`` to this type's native bit width."""

        bits = _strict_index(value) & ((1 << cls.BITS) - 1)
        return cls.from_bits(bits)

    @classmethod
    def _coerce(cls, value: SupportsIndex, /) -> Self:
        """Convert a supported Python input to the precise scalar value."""

        return cls(value)

    @classmethod
    def _to_ctypes_value(cls, value: SupportsIndex, /) -> int:
        """Return a value accepted by a ctypes scalar field or array."""

        return int(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: SupportsIndex,
            /,
        ) -> None: ...


class CSChar(CInteger):
    """C ``signed char``."""

    __ctypesx_ctype__ = ctypes.c_byte
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CUChar(CInteger):
    """C ``unsigned char``."""

    __ctypesx_ctype__ = ctypes.c_ubyte
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CShort(CInteger):
    """C ``short``."""

    __ctypesx_ctype__ = ctypes.c_short
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CUShort(CInteger):
    """C ``unsigned short``."""

    __ctypesx_ctype__ = ctypes.c_ushort
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CInt(CInteger):
    """C ``int``."""

    __ctypesx_ctype__ = ctypes.c_int
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CUInt(CInteger):
    """C ``unsigned int``."""

    __ctypesx_ctype__ = ctypes.c_uint
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CLong(CInteger):
    """C ``long`` using the host ABI."""

    __ctypesx_ctype__ = ctypes.c_long
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CULong(CInteger):
    """C ``unsigned long`` using the host ABI."""

    __ctypesx_ctype__ = ctypes.c_ulong
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CLongLong(CInteger):
    """C ``long long`` using the host ABI."""

    __ctypesx_ctype__ = ctypes.c_longlong
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CULongLong(CInteger):
    """C ``unsigned long long`` using the host ABI."""

    __ctypesx_ctype__ = ctypes.c_ulonglong
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class S8(CInteger):
    __ctypesx_ctype__ = ctypes.c_int8
    BITS = 8
    SIGNED = True


class U8(CInteger):
    __ctypesx_ctype__ = ctypes.c_uint8
    BITS = 8
    SIGNED = False


class S16(CInteger):
    __ctypesx_ctype__ = ctypes.c_int16
    BITS = 16
    SIGNED = True


class U16(CInteger):
    __ctypesx_ctype__ = ctypes.c_uint16
    BITS = 16
    SIGNED = False


class S32(CInteger):
    __ctypesx_ctype__ = ctypes.c_int32
    BITS = 32
    SIGNED = True


class U32(CInteger):
    __ctypesx_ctype__ = ctypes.c_uint32
    BITS = 32
    SIGNED = False


class S64(CInteger):
    __ctypesx_ctype__ = ctypes.c_int64
    BITS = 64
    SIGNED = True


class U64(CInteger):
    __ctypesx_ctype__ = ctypes.c_uint64
    BITS = 64
    SIGNED = False


class CSize(CInteger):
    """C ``size_t``."""

    __ctypesx_ctype__ = ctypes.c_size_t
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CSSize(CInteger):
    """C ``ssize_t`` on platforms where ctypes exposes it."""

    __ctypesx_ctype__ = ctypes.c_ssize_t
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CIntPtr(CInteger):
    """C ``intptr_t`` represented by the host pointer-sized signed type."""

    __ctypesx_ctype__ = ctypes.c_ssize_t
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = True


class CUIntPtr(CInteger):
    """C ``uintptr_t`` represented by the host pointer-sized unsigned type."""

    __ctypesx_ctype__ = ctypes.c_size_t
    BITS = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED = False


class CBool(int, metaclass=_CScalarMeta):
    """C ``_Bool`` accepting only Python bool or integer 0/1."""

    __ctypesx_ctype__: ClassVar[_CtypesScalarType] = ctypes.c_bool
    BITS: ClassVar[int] = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED: ClassVar[bool] = False

    def __new__(cls, value: bool | SupportsIndex = False, /) -> Self:
        return int.__new__(cls, _bool_index(value))

    @classmethod
    def _coerce(cls, value: bool | SupportsIndex, /) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(
        cls,
        value: bool | SupportsIndex,
        /,
    ) -> bool:
        return bool(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: bool | SupportsIndex,
            /,
        ) -> None: ...


class CChar(int, metaclass=_CScalarMeta):
    """One C ``char`` represented as an unsigned byte value.

    A string input must contain exactly one ASCII character.  A bytes input
    may contain any single byte, and integer inputs span the complete 0..255
    raw-byte range regardless of whether plain C ``char`` is signed locally.
    """

    __ctypesx_ctype__: ClassVar[_CtypesScalarType] = ctypes.c_char
    BITS: ClassVar[int] = ctypes.sizeof(__ctypesx_ctype__) * 8
    SIGNED: ClassVar[bool] = False

    def __new__(
        cls,
        value: str | bytes | SupportsIndex = 0,
        /,
    ) -> Self:
        if isinstance(value, str):
            if len(value) != 1 or not value.isascii():
                raise ValueError(
                    "CChar string input must be exactly one ASCII character"
                )
            number = ord(value)
        elif isinstance(value, bytes):
            if len(value) != 1:
                raise ValueError("CChar bytes input must have length 1")
            number = value[0]
        else:
            number = _strict_index(value)
        if not 0 <= number <= 0xFF:
            raise OverflowError(
                f"{number} is outside CChar range [0, 255]"
            )
        return int.__new__(cls, number)

    @classmethod
    def _coerce(
        cls,
        value: str | bytes | SupportsIndex,
        /,
    ) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(
        cls,
        value: str | bytes | SupportsIndex,
        /,
    ) -> bytes:
        return bytes((int(cls._coerce(value)),))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: str | bytes | SupportsIndex,
            /,
        ) -> None: ...


class CWChar(str, metaclass=_CScalarMeta):
    """Exactly one host-native C ``wchar_t`` value."""

    __ctypesx_ctype__: ClassVar[_CtypesScalarType] = ctypes.c_wchar
    BITS: ClassVar[int] = ctypes.sizeof(__ctypesx_ctype__) * 8

    def __new__(cls, value: str = "\0", /) -> Self:
        if len(value) != 1:
            raise ValueError("CWChar input must contain exactly one character")
        try:
            native_value = ctypes.c_wchar(value).value
        except (TypeError, ValueError):
            raise ValueError(
                f"{value!r} is not representable as one host wchar_t"
            ) from None
        return str.__new__(cls, native_value)

    @classmethod
    def _coerce(cls, value: str, /) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(cls, value: str, /) -> str:
        return str(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(self, instance: object, value: str, /) -> None: ...


class _CFloatBase(float, metaclass=_CScalarMeta):
    """Shared checked conversion for native C floating-point values."""

    __ctypesx_ctype__: ClassVar[_CtypesScalarType]

    def __new__(
        cls,
        value: SupportsFloat | SupportsIndex = 0.0,
        /,
    ) -> Self:
        if isinstance(value, (str, bytes, bytearray, bool)):
            raise TypeError(
                f"expected a real number, got {type(value).__name__}"
            )
        try:
            number = float(value)
        except OverflowError:
            raise OverflowError(
                f"{value!r} is outside {cls.__name__} range"
            ) from None
        except (TypeError, ValueError):
            raise TypeError(
                f"expected a real number, got {type(value).__name__}"
            ) from None
        native = cls.__ctypesx_ctype__(number).value
        native_number = cast(float, native)
        if math.isfinite(number) and math.isinf(native_number):
            raise OverflowError(
                f"{number!r} is outside {cls.__name__} finite range"
            )
        return float.__new__(cls, native_number)

    @classmethod
    def _coerce(
        cls,
        value: SupportsFloat | SupportsIndex,
        /,
    ) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsFloat | SupportsIndex,
        /,
    ) -> float:
        return float(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: SupportsFloat | SupportsIndex,
            /,
        ) -> None: ...


class CFloat(_CFloatBase):
    __ctypesx_ctype__ = ctypes.c_float


class CDouble(_CFloatBase):
    __ctypesx_ctype__ = ctypes.c_double


class CLongDouble(_CFloatBase):
    __ctypesx_ctype__ = ctypes.c_longdouble


class _CComplexBase(complex, metaclass=_CScalarMeta):
    """Shared checked conversion for native C complex values."""

    __ctypesx_ctype__: ClassVar[_CtypesScalarType]

    def __new__(
        cls,
        value: SupportsComplex | SupportsFloat | SupportsIndex = 0j,
        /,
    ) -> Self:
        if isinstance(value, (str, bytes, bytearray, bool)):
            raise TypeError(
                f"expected a numeric value, got {type(value).__name__}"
            )
        try:
            number = complex(value)
        except OverflowError:
            raise OverflowError(
                f"{value!r} is outside {cls.__name__} range"
            ) from None
        except (TypeError, ValueError):
            raise TypeError(
                f"expected a numeric value, got {type(value).__name__}"
            ) from None

        ctype = getattr(cls, "__ctypesx_ctype__", None)
        if ctype is None:
            raise NotImplementedError(
                f"{cls.__name__} is unavailable because this Python/"
                "libffi build has no matching C complex type"
            )
        native = cast(_CtypesScalarType, ctype)(number).value
        native_number = cast(complex, native)
        real_overflow = math.isfinite(number.real) and math.isinf(
            native_number.real
        )
        imag_overflow = math.isfinite(number.imag) and math.isinf(
            native_number.imag
        )
        if real_overflow or imag_overflow:
            raise OverflowError(
                f"{number!r} is outside {cls.__name__} finite range"
            )
        return complex.__new__(cls, native_number)

    @classmethod
    def _coerce(
        cls,
        value: SupportsComplex | SupportsFloat | SupportsIndex,
        /,
    ) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsComplex | SupportsFloat | SupportsIndex,
        /,
    ) -> complex:
        return complex(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: SupportsComplex | SupportsFloat | SupportsIndex,
            /,
        ) -> None: ...


_c_float_complex = getattr(ctypes, "c_float_complex", None)
_c_double_complex = getattr(ctypes, "c_double_complex", None)
_c_longdouble_complex = getattr(ctypes, "c_longdouble_complex", None)


class CFloatComplex(_CComplexBase):
    if TYPE_CHECKING:
        __ctypesx_ctype__ = ctypes.c_float_complex
    elif _c_float_complex is not None:
        __ctypesx_ctype__ = _c_float_complex


class CDoubleComplex(_CComplexBase):
    if TYPE_CHECKING:
        __ctypesx_ctype__ = ctypes.c_double_complex
    elif _c_double_complex is not None:
        __ctypesx_ctype__ = _c_double_complex


class CLongDoubleComplex(_CComplexBase):
    if TYPE_CHECKING:
        __ctypesx_ctype__ = ctypes.c_longdouble_complex
    elif _c_longdouble_complex is not None:
        __ctypesx_ctype__ = _c_longdouble_complex


# More verbose spellings and standard typedef spellings are aliases: they
# intentionally describe the same Python value type and the same C layout.
CSignedChar = CSChar
CUnsignedChar = CUChar
CUnsignedShort = CUShort
CUnsignedInt = CUInt
CUnsignedLong = CULong
CUnsignedLongLong = CULongLong
CInt8 = S8
CUInt8 = U8
CInt16 = S16
CUInt16 = U16
CInt32 = S32
CUInt32 = U32
CInt64 = S64
CUInt64 = U64
CSizeT = CSize
CSSizeT = CSSize
CIntPtrT = CIntPtr
CUIntPtrT = CUIntPtr
