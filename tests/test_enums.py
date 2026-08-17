from __future__ import annotations

# pyright: reportPrivateUsage=false

from enum import EJECT, STRICT
from typing import SupportsIndex, assert_type, cast

import pytest

from ctypesx.enums import (
    CEnum,
    CFlag,
    CIntEnum,
    CIntPtrFlag,
    CLongLongEnum,
    CShortEnum,
    CULongFlag,
    S8Enum,
    S8Flag,
    U8Enum,
    U8Flag,
    U16Enum,
    U32Enum,
    U64Enum,
)
from ctypesx.field import Field
from ctypesx.records import CStruct
from ctypesx.scalar import (
    CInt,
    CIntPtr,
    CInteger,
    CLongLong,
    CShort,
    CULong,
    S8,
    U8,
    U16,
    U32,
    U64,
)


class _Mode(U8Enum):
    OFF = 0
    ON = 1


class _SignedMode(S8Enum):
    NEGATIVE = -1
    POSITIVE = 1


class _Feature(U8Flag):
    READ = 1 << 0
    WRITE = 1 << 1


class _DirectEnum(CEnum, underlying=U16):
    VALUE = 7


class _DirectFlag(CFlag, underlying=U16):
    VALUE = 1


class _SignedFeature(S8Flag):
    LOW = 1
    HIGH = 0x80


class _SignedFlagHolder(CStruct):
    flags: _SignedFeature = Field()


def test_fixed_underlying_enum_value_has_exact_static_and_runtime_type() -> None:
    assert_type(_Mode.ON.value, U8)
    assert_type(_SignedMode.NEGATIVE.value, S8)
    assert type(_Mode.ON.value) is U8
    assert type(_SignedMode.NEGATIVE.value) is S8

    # The general class-keyword form is exact at runtime.  Python's type
    # system cannot derive a dependent return type from a class keyword, so
    # fixed-underlying convenience bases provide the static precision above.
    assert_type(_DirectEnum.VALUE.value, CInteger)
    assert type(_DirectEnum.VALUE.value) is U16


def test_no_underlying_integer_type_is_assumed() -> None:
    with pytest.raises(TypeError, match="must declare underlying"):

        class _MissingUnderlying(CEnum):  # pyright: ignore[reportUnusedClass]
            VALUE = 1


def test_closed_enum_rejects_unknown_and_out_of_range_values() -> None:
    assert _Mode(1) is _Mode.ON
    assert _Mode._coerce(1) is _Mode.ON
    assert _Mode._to_ctypes_value(_Mode.ON) == 1

    with pytest.raises(ValueError):
        _Mode(2)
    with pytest.raises(OverflowError):
        _Mode(256)
    with pytest.raises(TypeError):
        _Mode(True)
    with pytest.raises(TypeError):
        _Mode(cast(SupportsIndex, 1.0))


def test_enum_members_are_checked_when_the_class_is_created() -> None:
    with pytest.raises(OverflowError):

        class _OutOfRange(U8Enum):  # pyright: ignore[reportUnusedClass]
            VALUE = 256

    with pytest.raises(TypeError):

        class _BoolMember(U8Enum):  # pyright: ignore[reportUnusedClass]
            VALUE = True


def test_flag_combinations_and_unknown_bits_keep_exact_underlying_type() -> None:
    combined = _Feature.READ | _Feature.WRITE
    unknown = _Feature(1 << 7)
    mixed = combined | unknown

    assert_type(combined, _Feature)
    assert_type(combined.value, U8)
    assert type(combined.value) is U8
    assert type(unknown.value) is U8
    assert type(mixed.value) is U8
    assert int(mixed) == 0x83

    assert ~_Feature.READ is _Feature.WRITE
    assert type((~_Feature.READ).value) is U8


def test_flag_is_bounded_by_underlying_integer_type() -> None:
    assert int(_Feature(255)) == 255
    assert _DirectFlag(1) is _DirectFlag.VALUE

    with pytest.raises(OverflowError):
        _Feature(256)
    with pytest.raises(OverflowError):
        _Feature(-1)
    with pytest.raises(TypeError):
        _Feature(True)


def test_signed_flags_use_unsigned_patterns_and_signed_storage_values() -> None:
    class _SignedFlag(CFlag, underlying=S8):
        LOW = 1
        HIGH = 0x80

    assert int(_SignedFlag.HIGH) == 0x80
    assert type(_SignedFlag.HIGH.value) is S8
    assert _SignedFlag.HIGH.value == S8(-128)
    assert _SignedFlag(-128) is _SignedFlag.HIGH

    combined = _SignedFlag.LOW | _SignedFlag.HIGH
    assert int(combined) == 0x81
    assert combined.value == S8(-127)
    assert _SignedFlag._to_ctypes_value(0x81) == -127

    all_bits = _SignedFlag(-1)
    assert int(all_bits) == 0xFF
    assert all_bits.value == S8(-1)

    with pytest.raises(OverflowError):
        _SignedFlag(0x100)
    with pytest.raises(OverflowError):
        _SignedFlag(-129)


def test_signed_flag_round_trips_through_a_record_field() -> None:
    holder = _SignedFlagHolder(flags=0x80)

    assert holder.flags is _SignedFeature.HIGH
    assert int(holder.flags) == 0x80
    assert holder.flags.value == S8(-128)
    holder.flags = -127
    assert int(holder.flags) == 0x81


@pytest.mark.parametrize("boundary", (STRICT, EJECT))
def test_flags_keep_membership_for_unknown_bits(boundary: object) -> None:
    with pytest.raises(TypeError, match="boundary=enum.KEEP"):

        class _InvalidBoundary(  # pyright: ignore[reportUnusedClass]
            CFlag,
            underlying=U8,
            boundary=boundary,  # pyright: ignore[reportArgumentType]
        ):
            VALUE = 1


def test_representation_metadata_is_stable() -> None:
    assert _Mode.__ctypesx_underlying__ is U8
    assert _Mode.__ctypesx_ctype__ is U8.__ctypesx_ctype__

    with pytest.raises(TypeError, match="immutable C representation"):
        setattr(_Mode, "__ctypesx_underlying__", U16)
    with pytest.raises(TypeError, match="immutable C representation"):
        delattr(_Mode, "__ctypesx_ctype__")


def test_public_fixed_bases_cover_common_native_and_fixed_types() -> None:
    class _CIntValue(CIntEnum):
        VALUE = 1

    class _U16Value(U16Enum):
        VALUE = 1

    class _U32Value(U32Enum):
        VALUE = 1

    class _U64Value(U64Enum):
        VALUE = 1

    class _CULongValue(CULongFlag):
        VALUE = 1

    class _CShortValue(CShortEnum):
        VALUE = 1

    class _CLongLongValue(CLongLongEnum):
        VALUE = 1

    class _CIntPtrValue(CIntPtrFlag):
        VALUE = 1

    assert_type(_CIntValue.VALUE.value, CInt)
    assert_type(_U16Value.VALUE.value, U16)
    assert_type(_U32Value.VALUE.value, U32)
    assert_type(_U64Value.VALUE.value, U64)
    assert_type(_CULongValue.VALUE.value, CULong)
    assert_type(_CShortValue.VALUE.value, CShort)
    assert_type(_CLongLongValue.VALUE.value, CLongLong)
    assert_type(_CIntPtrValue.VALUE.value, CIntPtr)
