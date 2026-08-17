"""Strict checks for root re-exports and less common field categories."""

from __future__ import annotations

from typing import Any, SupportsIndex, assert_type

from ctypesx import (
    CBool,
    CChar,
    CFloat,
    CFloatComplex,
    CStruct,
    ConstPointer,
    ConstSpan,
    CWChar,
    Field,
    FieldInfo,
    FunctionPointer,
    Pointer,
    Span,
    U8,
    U8Enum,
    U16Flag,
    field_info,
    pointer_to,
)


class Mode(U8Enum):
    OFF = 0
    ON = 1


class Features(U16Flag):
    READ = 1
    WRITE = 2


type Callback = FunctionPointer[[U8], U8]
type BinaryCallback = FunctionPointer[[U8, U8], U8]


def increment(value: U8) -> U8:
    return U8(value + 1)


def add(left: U8, right: U8) -> U8:
    return U8(left + right)


class Record(CStruct):
    wide: CWChar = Field()
    ratio: CFloat = Field()
    number: CFloatComplex = Field()
    mode: Mode = Field()
    features: Features = Field()
    callback: Callback = Field()


class Api(CStruct):
    callback: BinaryCallback = Field()


class FakePointee:
    def __index__(self) -> int:
        return 0

    @classmethod
    def _to_ctypes_value(
        cls,
        value: SupportsIndex,
        /,
    ) -> object:
        return value


record = Record(
    wide="A",
    ratio=1.25,
    number=1 + 2j,
    mode=1,
    features=3,
    callback=increment,
)

assert_type(record.wide, CWChar)
assert_type(record.ratio, CFloat)
assert_type(record.number, CFloatComplex)
assert_type(record.mode, Mode)
assert_type(record.features, Features)
assert_type(record.callback, Callback)
assert_type(record.callback(U8(1)), U8)

record.wide = "B"
record.mode = 0
record.features = Features.READ
record.callback = 0x1234

api = Api(callback=add)
assert_type(api.callback(U8(1), U8(2)), U8)
api.callback(U8(1))  # pyright: ignore[reportCallIssue]
Api(callback=increment)  # pyright: ignore[reportArgumentType]

Record(mode=object())  # pyright: ignore[reportArgumentType]
Record(unknown=object())  # pyright: ignore[reportCallIssue]

assert_type(field_info(Record, "mode"), FieldInfo[Any])
assert_type(pointer_to(U8(1)), Pointer[U8])
assert_type(pointer_to(record), Pointer[Record])
assert_type(pointer_to(True, CBool), Pointer[CBool])
assert_type(pointer_to("A", CChar), Pointer[CChar])
assert_type(pointer_to("A", CWChar), Pointer[CWChar])
assert_type(pointer_to(1, Mode), Pointer[Mode])
pointer_to(object(), U8)  # pyright: ignore[reportCallIssue, reportArgumentType]
pointer_to(1, FakePointee)  # pyright: ignore[reportCallIssue, reportArgumentType]

span = Span[U8]([1, 2])
assert_type(span[0], U8)
span[0] = 3
span[0] = object()  # pyright: ignore[reportCallIssue, reportArgumentType]
Span[U8](0x1234)  # pyright: ignore[reportCallIssue, reportArgumentType]

readonly_span = ConstSpan[U8](ConstPointer[U8]([1, 2]))
assert_type(readonly_span[0], U8)
readonly_span[0] = 3  # pyright: ignore[reportArgumentType]
Span[U8](ConstPointer[U8]([1]))  # pyright: ignore[reportCallIssue, reportArgumentType]


def mutate_span(value: Span[U8]) -> None:
    value[0] = 7


mutate_span(readonly_span)  # pyright: ignore[reportArgumentType]
