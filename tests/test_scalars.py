from __future__ import annotations

# pyright: reportPrivateUsage=false

import ctypes
from typing import Any, SupportsIndex, assert_type, cast

import pytest

from ctypesx.scalar import (
    CBool,
    CChar,
    CDouble,
    CDoubleComplex,
    CFloat,
    CFloatComplex,
    CInt,
    CInteger,
    CIntPtr,
    CLong,
    CLongDouble,
    CLongDoubleComplex,
    CLongLong,
    CShort,
    CSChar,
    CSize,
    CSSize,
    CUChar,
    CUInt,
    CUIntPtr,
    CULong,
    CULongLong,
    CUShort,
    CWChar,
    S8,
    S16,
    S32,
    S64,
    U8,
    U16,
    U32,
    U64,
)


INTEGER_TYPES: tuple[type[CInteger], ...] = (
    CSChar,
    CUChar,
    CShort,
    CUShort,
    CInt,
    CUInt,
    CLong,
    CULong,
    CLongLong,
    CULongLong,
    S8,
    U8,
    S16,
    U16,
    S32,
    U32,
    S64,
    U64,
    CSize,
    CSSize,
    CIntPtr,
    CUIntPtr,
)


@pytest.mark.parametrize("scalar", INTEGER_TYPES)
def test_integer_range_is_derived_from_host_ctypes(
    scalar: type[CInteger],
) -> None:
    assert scalar.BITS == ctypes.sizeof(scalar.__ctypesx_ctype__) * 8

    minimum, maximum = scalar.bounds()
    assert type(scalar(minimum)) is scalar
    assert type(scalar(maximum)) is scalar
    assert scalar(minimum) == minimum
    assert scalar(maximum) == maximum

    with pytest.raises(OverflowError):
        scalar(minimum - 1)
    with pytest.raises(OverflowError):
        scalar(maximum + 1)


@pytest.mark.parametrize("scalar", INTEGER_TYPES)
def test_ordinary_integer_types_reject_bool_and_non_integer(
    scalar: type[CInteger],
) -> None:
    with pytest.raises(TypeError):
        scalar(True)
    with pytest.raises(TypeError):
        scalar(cast(SupportsIndex, 1.25))


class _IndexValue:
    def __init__(self, value: int) -> None:
        self._value = value

    def __index__(self) -> int:
        return self._value


def test_integer_types_accept_the_integer_protocol_without_truncation() -> None:
    assert U8(_IndexValue(255)) == 255

    with pytest.raises(OverflowError):
        U8(_IndexValue(256))
    with pytest.raises(OverflowError):
        U8(-1)

    assert U8.wrap(-1) == U8(255)
    assert S8.from_bits(255) == S8(-1)


class _DirectUnsignedShort(CInteger):
    __ctypesx_ctype__ = ctypes.c_ushort
    SIGNED = False


def test_direct_integer_subclass_gets_checked_host_width() -> None:
    assert _DirectUnsignedShort.BITS == ctypes.sizeof(ctypes.c_ushort) * 8
    assert _DirectUnsignedShort(1) == 1


def test_direct_integer_subclass_requires_an_integer_ctype() -> None:
    with pytest.raises(TypeError, match="not a ctypes integer type"):

        class _FloatBackedInteger(  # pyright: ignore[reportUnusedClass]
            CInteger
        ):
            __ctypesx_ctype__ = ctypes.c_float
            SIGNED = True


def test_direct_integer_subclass_validates_signedness() -> None:
    with pytest.raises(TypeError, match="disagrees.*signedness"):

        class _WrongSignedness(CInteger):  # pyright: ignore[reportUnusedClass]
            __ctypesx_ctype__ = ctypes.c_uint8
            SIGNED = True

    with pytest.raises(TypeError, match="SIGNED must be bool"):

        class _NonBooleanSignedness(  # pyright: ignore[reportUnusedClass]
            CInteger
        ):
            __ctypesx_ctype__ = ctypes.c_uint8
            SIGNED = cast(bool, 0)


def test_scalar_conversion_entry_points_are_precisely_typed() -> None:
    assert_type(U8._coerce(1), U8)
    assert_type(CBool._coerce(True), CBool)
    assert_type(CChar._coerce("A"), CChar)
    assert_type(CWChar._coerce("A"), CWChar)
    assert_type(CFloat._coerce(1), CFloat)
    if hasattr(CFloatComplex, "__ctypesx_ctype__"):
        assert_type(CFloatComplex._coerce(1 + 2j), CFloatComplex)

    assert U8._to_ctypes_value(255) == 255
    assert CBool._to_ctypes_value(1) is True
    assert CChar._to_ctypes_value("A") == b"A"
    assert CWChar._to_ctypes_value("A") == "A"


@pytest.mark.parametrize(
    ("value", "expected"),
    ((False, 0), (True, 1), (0, 0), (1, 1)),
)
def test_c_bool_accepts_only_bool_or_integer_zero_one(
    value: bool | int,
    expected: int,
) -> None:
    result = CBool(value)

    assert type(result) is CBool
    assert result == expected


@pytest.mark.parametrize("value", (-1, 2, 100))
def test_c_bool_rejects_other_integers(value: int) -> None:
    with pytest.raises(ValueError):
        CBool(value)


def test_c_char_accepts_ascii_bytes_and_full_raw_byte_range() -> None:
    assert CChar("A") == 0x41
    assert CChar(b"A") == 0x41
    assert CChar(b"\xff") == 0xFF
    assert CChar(0) == 0
    assert CChar(255) == 255

    with pytest.raises(ValueError):
        CChar("")
    with pytest.raises(ValueError):
        CChar("AB")
    with pytest.raises(ValueError):
        CChar("é")
    with pytest.raises(ValueError):
        CChar(b"")
    with pytest.raises(ValueError):
        CChar(b"AB")
    with pytest.raises(OverflowError):
        CChar(-1)
    with pytest.raises(OverflowError):
        CChar(256)
    with pytest.raises(TypeError):
        CChar(True)


def test_c_wchar_is_exactly_one_host_wchar() -> None:
    assert type(CWChar("A")) is CWChar
    assert CWChar("A") == "A"
    assert ctypes.c_wchar(CWChar._to_ctypes_value("A")).value == "A"

    with pytest.raises(ValueError):
        CWChar("")
    with pytest.raises(ValueError):
        CWChar("AB")


@pytest.mark.parametrize(
    ("scalar", "expected"),
    (
        (CFloat, ctypes.c_float(1.2).value),
        (CDouble, ctypes.c_double(1.2).value),
        (CLongDouble, ctypes.c_longdouble(1.2).value),
    ),
)
def test_floating_scalars_use_the_native_ctypes_conversion(
    scalar: type[CFloat] | type[CDouble] | type[CLongDouble],
    expected: float,
) -> None:
    value = scalar(1.2)

    assert type(value) is scalar
    assert value == expected
    with pytest.raises(TypeError):
        scalar(True)
    with pytest.raises(TypeError):
        scalar(cast(float, "1.2"))


def test_finite_float_overflow_is_not_silently_converted_to_infinity() -> None:
    with pytest.raises(OverflowError):
        CFloat(1e100)

    assert CFloat(float("inf")) == float("inf")
    assert CFloat(float("-inf")) == float("-inf")


_COMPLEX_CASES: tuple[tuple[type[complex], type[Any]], ...] = tuple(
    (scalar, ctype)
    for scalar, name in (
        (CFloatComplex, "c_float_complex"),
        (CDoubleComplex, "c_double_complex"),
        (CLongDoubleComplex, "c_longdouble_complex"),
    )
    if (ctype := getattr(ctypes, name, None)) is not None
)


@pytest.mark.parametrize(("scalar", "ctype"), _COMPLEX_CASES)
def test_complex_scalars_use_native_ctypes_quantization(
    scalar: (
        type[CFloatComplex]
        | type[CDoubleComplex]
        | type[CLongDoubleComplex]
    ),
    ctype: type[Any],
) -> None:
    value = scalar(1.2 + 3.4j)
    expected = ctype(1.2 + 3.4j).value

    assert type(value) is scalar
    assert value == expected
    assert scalar._to_ctypes_value(value) == expected

    for invalid in (True, "1+2j", b"1+2j", bytearray(b"1+2j")):
        with pytest.raises(TypeError):
            scalar(cast(complex, invalid))


@pytest.mark.skipif(
    not hasattr(CFloatComplex, "__ctypesx_ctype__"),
    reason="host ctypes has no C complex support",
)
def test_finite_complex_overflow_is_not_silently_converted_to_infinity() -> None:
    with pytest.raises(OverflowError):
        CFloatComplex(1e100 + 1j)

    infinity = complex(float("inf"), 1.0)
    assert CFloatComplex(infinity) == infinity


class _SemanticU8(U8):
    pass


@pytest.mark.parametrize("scalar", (U8, _SemanticU8))
def test_integer_representation_metadata_is_immutable(
    scalar: type[U8],
) -> None:
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(scalar, "BITS", 16)
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(scalar, "SIGNED", True)
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(scalar, "__ctypesx_ctype__", ctypes.c_uint16)
    with pytest.raises(TypeError, match="immutable C representation"):
        delattr(scalar, "BITS")


@pytest.mark.parametrize(
    "scalar",
    (
        CBool,
        CChar,
        CWChar,
        CFloat,
        CDouble,
        CLongDouble,
        CFloatComplex,
        CDoubleComplex,
        CLongDoubleComplex,
    ),
)
def test_all_scalar_representation_metadata_is_immutable(
    scalar: type[object],
) -> None:
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(scalar, "__ctypesx_ctype__", ctypes.c_int)
    with pytest.raises(TypeError, match="immutable C representation"):
        delattr(scalar, "__ctypesx_ctype__")
    if hasattr(scalar, "BITS"):
        with pytest.raises(TypeError, match="immutable C representation"):
            setattr(scalar, "BITS", 1)
        with pytest.raises(TypeError, match="immutable C representation"):
            delattr(scalar, "BITS")
    if hasattr(scalar, "SIGNED"):
        with pytest.raises(TypeError, match="immutable C representation"):
            setattr(scalar, "SIGNED", True)


def test_abstract_integer_metadata_cannot_be_added_after_creation() -> None:
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(CInteger, "BITS", 8)
    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(CInteger, "SIGNED", False)
