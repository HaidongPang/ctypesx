from __future__ import annotations

import ctypes
import gc
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, assert_type, cast

import pytest

from ctypesx.pointer import (
    CharPointer,
    ConstCharPointer,
    ConstPointer,
    ConstSpan,
    ConstWCharPointer,
    FunctionPointer,
    Pointer,
    Span,
    VoidPointer,
    WCharPointer,
    pointer_to,
)
from ctypesx.enums import U8Enum
from ctypesx.array import FamArray
from ctypesx.field import Field
from ctypesx.records import CStruct, field_info
from ctypesx.scalar import U8, U16


class _Mode(U8Enum):
    OFF = 0
    ON = 1


class _U8(int):
    __ctypesx_ctype__ = ctypes.c_uint8

    def __new__(cls, value: object = 0) -> _U8:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("U8 requires an integer")
        if not 0 <= value <= 0xFF:
            raise OverflowError("U8 is out of range")
        return int.__new__(cls, value)

    @classmethod
    def _to_ctypes_value(cls, value: object) -> int:
        return int(cls(value))

    if TYPE_CHECKING:

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> Self: ...

        def __set__(self, instance: object, value: int | Self, /) -> None: ...


def test_pointer_factory_maps_to_ctypes_pointer_and_is_cached() -> None:
    pointer_type = Pointer[_U8]

    assert pointer_type is Pointer[_U8]
    assert pointer_type.__ctypesx_ctype__ is pointer_type
    assert cast(Any, pointer_type)._type_ is ctypes.c_uint8
    assert issubclass(pointer_type, ctypes.POINTER(ctypes.c_uint8))
    assert ctypes.sizeof(pointer_type) == ctypes.sizeof(ctypes.c_void_p)


@pytest.mark.parametrize("address", [0, 1, 0x1234])
def test_raw_integer_is_a_pointer_address(address: int) -> None:
    pointer = Pointer[_U8](address)

    assert pointer.address == address
    assert pointer.known_length is None
    assert pointer.is_null is (address == 0)


@pytest.mark.parametrize(
    "value, error",
    [
        (True, TypeError),
        (-1, OverflowError),
        (1 << (ctypes.sizeof(ctypes.c_void_p) * 8), OverflowError),
        (object(), TypeError),
    ],
)
def test_raw_pointer_address_is_checked(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        Pointer[_U8](value)


def test_sequence_is_converted_recursively_to_an_owned_snapshot() -> None:
    source = [1, 2, 3]
    pointer = Pointer[_U8](source)

    source[0] = 99
    assert pointer.known_length == 3
    assert [pointer[index] for index in range(3)] == [_U8(1), _U8(2), _U8(3)]
    assert all(type(pointer[index]) is _U8 for index in range(3))

    pointer[1] = 7
    assert pointer[1] == _U8(7)
    assert source == [99, 2, 3]


def test_sequence_conversion_is_atomic() -> None:
    with pytest.raises(OverflowError):
        Pointer[_U8]([1, 256, 3])


def test_pointer_read_does_not_degrade_invalid_semantic_value_to_int() -> None:
    pointer = Pointer[_Mode]([_Mode.ON])
    raw = ctypes.cast(cast(Any, pointer), ctypes.POINTER(ctypes.c_uint8))
    raw[0] = 2

    with pytest.raises(ValueError):
        _ = pointer[0]


def test_empty_sequence_is_owned_non_null_zero_length_buffer() -> None:
    pointer = Pointer[_U8]([])

    assert pointer.known_length == 0
    assert not pointer.is_null


def test_backing_survives_pointer_and_ctypes_structure_copies() -> None:
    pointer_type = Pointer[_U8]
    pointer = pointer_type([10, 20])
    owner = cast(Any, pointer)._ctypesx_owner
    owner_reference = weakref.ref(owner)

    class Holder(ctypes.Structure):
        _fields_ = [("values", cast(Any, pointer_type))]

    holder = Holder(pointer)
    del pointer, owner
    gc.collect()

    assert owner_reference() is not None
    assert holder.values[0] == 10
    assert holder.values[1] == 20


def test_pointer_record_conversion_hooks_preserve_owned_identity() -> None:
    pointer_type = Pointer[_U8]
    raw, owner = cast(Any, pointer_type)._to_ctypes_assignment([1, 2])

    restored = cast(Any, pointer_type)._from_ctypes_value(raw, owner)

    assert owner is raw
    assert restored is raw
    assert restored.known_length == 2


def test_pointer_record_conversion_hook_does_not_own_raw_address() -> None:
    pointer_type = Pointer[_U8]
    raw, owner = cast(Any, pointer_type)._to_ctypes_assignment(0x1234)

    restored = cast(Any, pointer_type)._from_ctypes_value(raw, owner)

    assert owner is None
    assert restored.address == 0x1234
    assert restored.known_length is None


def test_const_pointer_rejects_writes() -> None:
    pointer = ConstCharPointer("abc")

    assert ctypes.string_at(cast(Any, pointer)) == b"abc"
    with pytest.raises(TypeError, match="const pointer"):
        cast(Any, pointer)[0] = b"z"


def test_const_pointer_accepts_mutable_pointer_and_retains_backing() -> None:
    mutable = Pointer[_U8]([1, 2])
    backing_reference = weakref.ref(cast(Any, mutable)._ctypesx_owner)

    readonly = ConstPointer[_U8](mutable)
    del mutable
    gc.collect()

    assert backing_reference() is not None
    assert readonly.known_length == 2
    assert [readonly[0], readonly[1]] == [_U8(1), _U8(2)]
    with pytest.raises(TypeError, match="const pointer"):
        cast(Any, readonly)[0] = 3


def test_const_span_is_statically_distinct_and_read_only_at_runtime() -> None:
    readonly = ConstSpan[_U8](ConstPointer[_U8]([1, 2]))

    assert readonly.to_list() == [_U8(1), _U8(2)]
    assert readonly.pointer.is_const
    assert not isinstance(readonly, Span)
    with pytest.raises(TypeError, match="ConstSpan"):
        readonly[0] = cast(Any, 3)

    with pytest.raises(TypeError, match="ConstSpan"):
        Span[_U8](  # pyright: ignore[reportCallIssue]
            ConstPointer[_U8]([1])  # pyright: ignore[reportArgumentType]
        )

    with pytest.raises(TypeError, match="already parameterized"):
        cast(Any, ConstSpan[_U8])[_U8]


def test_const_char_pointer_accepts_mutable_char_pointer() -> None:
    mutable = CharPointer("ascii")
    readonly = ConstCharPointer(mutable)

    assert readonly.address == mutable.address
    assert readonly.known_length == 6
    assert ctypes.string_at(cast(Any, readonly)) == b"ascii"


@pytest.mark.parametrize("pointer_type", [CharPointer, ConstCharPointer])
def test_char_pointer_accepts_ascii_and_appends_nul(pointer_type: Any) -> None:
    pointer = pointer_type("hello")

    assert pointer.known_length == 6
    assert ctypes.string_at(pointer, 6) == b"hello\0"


@pytest.mark.parametrize("value", ["café", "a\0b"])
def test_char_pointer_rejects_non_ascii_or_embedded_nul(value: str) -> None:
    with pytest.raises(ValueError):
        CharPointer(value)


@pytest.mark.parametrize("pointer_type", [WCharPointer, ConstWCharPointer])
def test_wchar_pointer_accepts_python_string(pointer_type: Any) -> None:
    pointer = pointer_type("你好")

    assert ctypes.wstring_at(pointer) == "你好"
    assert pointer.known_length == 3


@pytest.mark.parametrize("value", [0, 0x1234])
def test_void_pointer_accepts_raw_address(value: int) -> None:
    pointer = VoidPointer(value)

    assert pointer.address == value
    assert pointer.is_null is (value == 0)


@pytest.mark.parametrize(
    "value, error",
    [
        (True, TypeError),
        (-1, OverflowError),
        (1 << (ctypes.sizeof(ctypes.c_void_p) * 8), OverflowError),
    ],
)
def test_void_pointer_validates_address(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        VoidPointer(cast(Any, value))


def test_void_pointer_from_owned_pointer_keeps_backing_alive() -> None:
    typed = Pointer[_U8]([42])
    owner_reference = weakref.ref(cast(Any, typed)._ctypesx_owner)
    erased = VoidPointer(typed)
    del typed
    gc.collect()

    assert owner_reference() is not None
    assert erased.address != 0


def test_function_pointer_accepts_and_keeps_callable_alive() -> None:
    callback_type = FunctionPointer[[ctypes.c_int], ctypes.c_int]

    def increment(value: int) -> int:
        return value + 1

    callback_reference = weakref.ref(increment)
    pointer = callback_type(increment)
    del increment
    gc.collect()

    assert callback_reference() is not None
    assert cast(Callable[[int], int], pointer)(41) == 42
    assert pointer.address != 0


def test_function_pointer_wraps_ctypesx_callback_arguments_and_result() -> None:
    callback_type = FunctionPointer[[_U8], _U8]
    received: list[tuple[_U8, type[_U8]]] = []

    def increment(value: _U8) -> _U8:
        received.append((value, type(value)))
        return _U8(value + 1)

    pointer = callback_type(increment)

    result = pointer(_U8(40))
    assert received == [(_U8(40), _U8)]
    assert result == _U8(41)
    assert type(result) is _U8


def test_function_pointer_lowers_and_restores_void_pointer_results() -> None:
    storage = ctypes.c_int(42)
    address = ctypes.addressof(storage)
    callback_type = FunctionPointer[[], VoidPointer]
    callback = callback_type(lambda: address)

    result = callback()

    assert result.address == address


def test_function_pointer_restores_raw_ctypes_pointer_results() -> None:
    storage = ctypes.c_int(42)
    raw_pointer_type = ctypes.POINTER(ctypes.c_int)
    raw_pointer = ctypes.pointer(storage)
    callback_type = FunctionPointer[[], raw_pointer_type]
    callback = callback_type(lambda: raw_pointer)

    result = callback()

    assert isinstance(result, raw_pointer_type)
    assert result.contents.value == 42


@pytest.mark.parametrize(
    ("result_type", "value"),
    [
        (ctypes.c_char_p, b"hello"),
        (ctypes.c_wchar_p, "hello"),
    ],
)
def test_function_pointer_retains_and_restores_raw_c_string_results(
    result_type: Any,
    value: bytes | str,
) -> None:
    callback_type = FunctionPointer[[], result_type]
    callback = callback_type(lambda: value)

    assert callback() == value
    raw_address = cast(Any, callback)._ctypesx_callback()
    gc.collect()
    restored = (
        ctypes.string_at(raw_address)
        if result_type is ctypes.c_char_p
        else ctypes.wstring_at(raw_address)
    )
    assert restored == value


def test_function_pointer_retains_owned_managed_pointer_result() -> None:
    callback_type = FunctionPointer[[], Pointer[_U8]]
    callback = callback_type(lambda: Pointer[_U8]([7]))

    result = callback()
    gc.collect()

    assert result.known_length == 1
    assert result[0] == _U8(7)


def test_callback_retains_every_owned_pointer_result_until_release() -> None:
    callback_type = FunctionPointer[[], Pointer[_U8]]
    callback = callback_type(lambda: Pointer[_U8]([7]))
    raw_callback = cast(Any, callback)._ctypesx_callback

    raw_callback()
    first = cast(Any, callback)._ctypesx_return_owners[0]
    first_backing = weakref.ref(first._ctypesx_owner)
    raw_callback()
    del first
    gc.collect()

    assert len(cast(Any, callback)._ctypesx_return_owners) == 2
    assert first_backing() is not None


def test_void_callback_result_pins_dynamic_record_until_callback_release() -> None:
    target = _DynamicChild(tag=2, payload=[3])
    callback_type = FunctionPointer[[], VoidPointer]
    callback = callback_type(lambda: pointer_to(target))

    result = callback()
    assert result.address == ctypes.addressof(target)
    with pytest.raises(BufferError, match="pinned"):
        target.payload.append(4)

    del callback
    gc.collect()
    target.payload.append(4)
    assert target.payload[-1] == U8(4)


def test_function_pointer_accepts_raw_address_without_dereferencing_it() -> None:
    callback_type = FunctionPointer[[ctypes.c_int], ctypes.c_int]
    pointer = callback_type(0x1234)

    assert pointer.address == 0x1234


@pytest.mark.parametrize(
    "value, error",
    [
        (True, TypeError),
        (-1, OverflowError),
        (1 << (ctypes.sizeof(ctypes.c_void_p) * 8), OverflowError),
    ],
)
def test_function_pointer_validates_raw_address(
    value: object, error: type[Exception]
) -> None:
    callback_type = FunctionPointer[[ctypes.c_int], ctypes.c_int]
    with pytest.raises(error):
        callback_type(value)


def test_span_from_sequence_is_bounded_owned_and_mutable() -> None:
    span = Span[_U8]([1, 2, 3])

    assert len(span) == 3
    assert span.to_list() == [_U8(1), _U8(2), _U8(3)]
    assert span[-1] == _U8(3)
    assert span[1:] == [_U8(2), _U8(3)]

    span[0] = 9
    span[1:] = [8, 7]
    assert list(span) == [_U8(9), _U8(8), _U8(7)]

    with pytest.raises(IndexError):
        _ = span[3]
    with pytest.raises(ValueError):
        span[:] = [1]


def test_span_slice_conversion_is_atomic() -> None:
    span = Span[_U8]([1, 2])

    with pytest.raises(OverflowError):
        span[:] = [3, 256]

    assert list(span) == [_U8(1), _U8(2)]


def test_span_raw_pointer_requires_explicit_length() -> None:
    with pytest.raises(TypeError, match="explicit Span length"):
        cast(Any, Span[_U8])(0x1234)

    empty = Span[_U8](None, 0)
    assert len(empty) == 0
    assert empty.address == 0

    with pytest.raises(ValueError, match="non-empty Span"):
        Span[_U8](None, 1)


def test_span_cannot_exceed_known_backing() -> None:
    pointer = Pointer[_U8]([1, 2])

    with pytest.raises(ValueError, match="known size"):
        Span[_U8](pointer, 3)


def test_pointer_to_infers_ctypesx_type_and_supports_with() -> None:
    value = _U8(37)

    with pointer_to(value) as pointer:
        assert pointer[0] == _U8(37)
        assert pointer.known_length == 1


def test_pointer_to_plain_python_value_requires_explicit_type() -> None:
    with pytest.raises(TypeError, match="explicit pointee"):
        cast(Any, pointer_to)(7)

    pointer = pointer_to(7, _U8)
    assert pointer[0] == _U8(7)


def test_pointer_to_ctypes_array_points_to_first_element_and_retains_it() -> None:
    array = (ctypes.c_uint8 * 3)(1, 2, 3)
    array_reference = weakref.ref(array)

    pointer = pointer_to(array)
    del array
    gc.collect()

    assert array_reference() is not None
    assert pointer.known_length == 3
    assert [pointer[index] for index in range(3)] == [1, 2, 3]


class _DynamicChild(CStruct):
    tag: U16 = Field()
    payload: FamArray[U8] = Field()


class _DynamicParent(CStruct):
    prefix: U16 = Field()
    child: _DynamicChild = Field()


class _DynamicPointerHolder(CStruct):
    target: Pointer[_DynamicChild] = Field()


class _DynamicVoidPointerHolder(CStruct):
    target: VoidPointer = Field()


def test_pointer_to_nested_dynamic_record_refreshes_after_parent_moves() -> None:
    parent = _DynamicParent(
        prefix=1,
        child=_DynamicChild(tag=2, payload=[3]),
    )
    held_child = parent.child
    pointer = pointer_to(held_child)

    # Force the root allocation to move while the held child still contains
    # its original native ctypes view address and after the pointer was made.
    original_address = pointer.address
    held_child.payload.extend(range(200))
    expected = (
        ctypes.addressof(parent)
        + field_info(_DynamicParent, "child").offset
    )
    stale_address = original_address if original_address != expected else 0
    cast(Any, pointer)._set_address_bits(stale_address)
    assert pointer.address != expected

    with pointer as pinned:
        assert pinned.address == expected
        assert ctypes.c_uint16.from_address(pinned.address).value == 2
        with pytest.raises(BufferError, match="pinned"):
            held_child.payload.append(4)


def test_pointer_to_fam_raw_view_pins_and_refreshes_its_record() -> None:
    parent = _DynamicParent(
        prefix=1,
        child=_DynamicChild(tag=2, payload=[3]),
    )
    child = parent.child
    held_raw = child.payload.raw
    pointer = pointer_to(held_raw)

    child.payload.extend(range(100))
    expected = (
        ctypes.addressof(parent)
        + field_info(_DynamicParent, "child").offset
        + field_info(_DynamicChild, "payload").offset
    )
    if pointer.address == expected:
        cast(Any, pointer)._set_address_bits(0)
    assert pointer.address != expected

    with pointer as pinned:
        assert pinned.address == expected
        assert pinned[0] == 3
        with pytest.raises(BufferError, match="pinned"):
            child.payload.append(4)

    child.payload.append(4)


def test_span_refreshes_record_backing_and_rejects_a_shrunken_view() -> None:
    child = _DynamicChild(tag=2, payload=[3, 4])
    pointer = pointer_to(child.payload.raw)
    span = Span[ctypes.c_uint8](pointer)

    original_address = span.address
    child.payload.extend([5] * 100_000)
    expected = (
        ctypes.addressof(child)
        + field_info(_DynamicChild, "payload").offset
    )

    assert span.address == expected
    assert span[0] == 3
    assert original_address != expected

    child.payload.clear()

    with pointer:
        assert pointer.known_length == 0
    with pytest.raises(BufferError, match="shorter"):
        len(span)


def test_pointer_field_pins_a_dynamic_target_until_replaced() -> None:
    target = _DynamicChild(tag=2, payload=[3])
    holder = _DynamicPointerHolder(target=pointer_to(target))
    field_address = ctypes.c_void_p.from_address(
        ctypes.addressof(holder)
        + field_info(_DynamicPointerHolder, "target").offset
    )

    assert field_address.value == ctypes.addressof(target)
    assert holder.target.address == ctypes.addressof(target)
    with pytest.raises(BufferError, match="pinned"):
        target.payload.extend([4] * 100)

    holder.target = None
    target.payload.append(4)

    assert list(target.payload) == [U8(3), U8(4)]


def test_pointer_field_refreshes_a_target_that_moved_before_assignment() -> None:
    target = _DynamicChild(tag=2, payload=[3])
    pointer = pointer_to(target)

    target.payload.extend([4] * 100_000)
    holder = _DynamicPointerHolder(target=pointer)

    assert holder.target.address == ctypes.addressof(target)
    with pytest.raises(BufferError, match="pinned"):
        target.payload.append(5)


def test_void_pointer_preserves_dynamic_record_relocation_and_field_pin() -> None:
    target = _DynamicChild(tag=2, payload=[3])
    typed = pointer_to(target)
    erased = VoidPointer(typed)

    target.payload.extend([4] * 100_000)
    assert erased.address == ctypes.addressof(target)

    holder = _DynamicVoidPointerHolder(target=erased)
    assert holder.target.address == ctypes.addressof(target)
    with pytest.raises(BufferError, match="pinned"):
        target.payload.append(5)

    holder.target = None
    target.payload.append(5)
    assert target.payload[-1] == U8(5)


if TYPE_CHECKING:
    typed_span = Span[_U8]([1, 2])
    typed_span[0] = 3
    typed_span[:] = [4, 5]
    typed_span[0] = object()  # pyright: ignore[reportCallIssue, reportArgumentType]
    typed_span[:] = [object()]  # pyright: ignore[reportCallIssue, reportArgumentType]

    assert_type(pointer_to(_U8(1)), Pointer[_U8])
    assert_type(pointer_to(1, _U8), Pointer[_U8])
    pointer_to(1)  # pyright: ignore[reportCallIssue, reportArgumentType]
