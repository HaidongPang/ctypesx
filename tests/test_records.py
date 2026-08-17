from __future__ import annotations

import ctypes
import gc
import weakref
from typing import Annotated, Any, assert_type, cast

import pytest

from ctypesx.array import Array, FamArray
from ctypesx.field import Bits, Field, Length
from ctypesx.pointer import CharPointer, FunctionPointer, Pointer, pointer_to
from ctypesx.records import CStruct, CUnion, field_info
from ctypesx.scalar import S8, U8, U16, U32


class _Packet(CStruct):
    count: U32 = Field()
    mode: Annotated[U8, Bits(3)] = Field()
    data: Annotated[Array[U8], Length(3)] = Field()
    tail: FamArray[U16] = Field()


class _Matrix(CStruct):
    values: Annotated[
        Array[Array[U8]],
        Length(2, 3),
    ] = Field()


class _Static(CStruct):
    value: U32 = Field()


class _DynamicChild(CStruct):
    tag: U16 = Field()
    payload: FamArray[U8] = Field()


class _DynamicParent(CStruct):
    prefix: U16 = Field()
    child: _DynamicChild = Field()


class _TailUnion(CUnion):
    bytes_: FamArray[U8] = Field()
    words: FamArray[U16] = Field()


class _UnionContainer(CStruct):
    prefix: U16 = Field()
    tail: _TailUnion = Field()


class _PointerRecord(CStruct):
    values: Pointer[U8] = Field()
    text: CharPointer = Field()


class _PointerArrays(CStruct):
    fixed: Annotated[Array[Pointer[U8]], Length(1)] = Field()
    nested: Annotated[
        Array[Array[Pointer[U8]]],
        Length(1, 1),
    ] = Field()
    callbacks: Annotated[
        Array[FunctionPointer[[ctypes.c_int], ctypes.c_int]],
        Length(1),
    ] = Field()
    count: U32 = Field()
    dynamic: FamArray[Pointer[U8]] = Field()


class _PointerElement(CStruct):
    values: Pointer[U8] = Field()


class _RecordElementArrays(CStruct):
    fixed: Annotated[Array[_PointerElement], Length(1)] = Field()
    count: U32 = Field()
    dynamic: FamArray[_PointerElement] = Field()


class _StaticChildParent(CStruct):
    child: _Static = Field()
    dynamic: FamArray[U8] = Field()


type _ByteAlias = U8
type _ChainedByteAlias = _ByteAlias
type _CallbackAlias = FunctionPointer[[U8], U8]
type _PairAlias = Annotated[Array[_ChainedByteAlias], Length(2)]
type _TailAlias = FamArray[_ByteAlias]
type _GenericArrayAlias[T] = Array[T]


class _AliasedFields(CStruct):
    value: _ChainedByteAlias = Field()
    pair: _PairAlias = Field()
    callback: _CallbackAlias = Field()


class _AliasedTail(CStruct):
    count: U8 = Field()
    values: _TailAlias = Field()


class _GenericAliasedArray(CStruct):
    values: Annotated[_GenericArrayAlias[U8], Length(2)] = Field()


def test_constructor_and_assignment_use_declared_type_conversion() -> None:
    packet = _Packet(
        count=7,
        mode=5,
        data=[1, 2, 3],
        tail=[10, 20],
    )

    assert_type(packet.count, U32)
    assert_type(packet.data, Array[U8])
    assert_type(packet.tail, FamArray[U16])
    assert type(packet.count) is U32
    assert type(packet.mode) is U8
    assert packet.count == 7
    assert packet.mode == 5
    assert list(packet.data) == [U8(1), U8(2), U8(3)]
    assert list(packet.tail) == [U16(10), U16(20)]

    packet.count = 9
    packet.data = [3, 2, 1]
    packet.tail = [30]

    assert packet.count == U32(9)
    assert list(packet.data) == [U8(3), U8(2), U8(1)]
    assert list(packet.tail) == [U16(30)]

    with pytest.raises(OverflowError):
        packet.count = 1 << 32
    with pytest.raises(OverflowError):
        packet.data = [1, 2, 256]
    with pytest.raises(ValueError):
        packet.data = [1, 2]


def test_pep_695_aliases_are_expanded_for_runtime_field_compilation() -> None:
    def increment(value: U8) -> U8:
        return U8(value + 1)

    record = _AliasedFields(
        value=1,
        pair=[2, 3],
        callback=increment,
    )
    tail = _AliasedTail(count=2, values=[4, 5])
    generic = _GenericAliasedArray(values=[6, 7])

    assert type(record.value) is U8
    assert list(record.pair) == [U8(2), U8(3)]
    assert record.callback(U8(8)) == U8(9)
    assert list(tail.values) == [U8(4), U8(5)]
    assert list(generic.values) == [U8(6), U8(7)]


def test_constructor_is_keyword_only_optional_and_zero_initializes() -> None:
    packet = _Packet()

    assert packet.count == U32(0)
    assert packet.mode == U8(0)
    assert list(packet.data) == [U8(0), U8(0), U8(0)]
    assert list(packet.tail) == []
    assert bytes(packet) == bytes(ctypes.sizeof(_Packet))

    with pytest.raises(TypeError):
        cast(Any, _Packet)(1)
    with pytest.raises(TypeError, match="no C field"):
        cast(Any, _Packet)(unknown=1)


def test_annotation_order_is_the_physical_field_order() -> None:
    assert field_info(_Packet, "count").offset == 0
    assert field_info(_Packet, "mode").offset == 4
    assert field_info(_Packet, "data").offset == 5
    assert field_info(_Packet, "tail").offset == ctypes.sizeof(_Packet)
    assert cast(Any, _Packet.count).offset == 0


def test_module_introspection_does_not_reserve_a_field_info_name() -> None:
    class HasFieldInfo(CStruct):
        field_info: U8 = Field()

    record = HasFieldInfo(field_info=7)

    assert record.field_info == U8(7)
    assert field_info(HasFieldInfo, "field_info").offset == 0


def test_bit_fields_are_checked_against_declared_width_and_signedness() -> None:
    packet = _Packet(mode=7)
    assert packet.mode == U8(7)

    with pytest.raises(OverflowError):
        packet.mode = 8

    class SignedBits(CStruct):
        value: Annotated[S8, Bits(3)] = Field()

    assert SignedBits(value=-4).value == S8(-4)
    assert SignedBits(value=3).value == S8(3)
    with pytest.raises(OverflowError):
        SignedBits(value=-5)
    with pytest.raises(OverflowError):
        SignedBits(value=4)


def test_invalid_field_declarations_fail_at_class_creation() -> None:
    with pytest.raises(TypeError, match=r"must be declared with Field\(\)"):

        class MissingMarker(CStruct):  # pyright: ignore[reportUnusedClass]
            value: U8

    with pytest.raises(ValueError, match="does not fit"):

        class OversizedBits(CStruct):  # pyright: ignore[reportUnusedClass]
            value: Annotated[U8, Bits(9)] = Field()

    with pytest.raises(TypeError, match="final field"):

        class NonFinalFam(CStruct):  # pyright: ignore[reportUnusedClass]
            count: U8 = Field()
            values: FamArray[U8] = Field()
            trailing: U8 = Field()

    with pytest.raises(TypeError, match="at most one"):

        class TwoTails(CStruct):  # pyright: ignore[reportUnusedClass]
            count: U8 = Field()
            first: FamArray[U8] = Field()
            second: FamArray[U8] = Field()

    with pytest.raises(TypeError, match="must follow"):

        class OnlyFam(CStruct):  # pyright: ignore[reportUnusedClass]
            values: FamArray[U8] = Field()

    for attribute, value in (
        ("_pack_", 1),
        ("_align_", 16),
        ("_layout_", "gcc-sysv"),
    ):
        with pytest.raises(TypeError, match=f"direct {attribute}"):
            cast(Any, type)(
                "DirectLayout",
                (CStruct,),
                {
                    attribute: value,
                    "__annotations__": {"value": U8},
                    "value": Field(),
                },
            )


def test_fixed_and_nested_arrays_are_zero_copy_checked_views() -> None:
    matrix = _Matrix(values=[[1, 2, 3], [4, 5, 6]])
    view = matrix.values

    assert list(view[0]) == [U8(1), U8(2), U8(3)]
    assert list(view[1]) == [U8(4), U8(5), U8(6)]
    view[1][0] = 9
    assert matrix.values[1][0] == U8(9)

    matrix.values = [[10, 11, 12], [13, 14, 15]]
    assert list(view[0]) == [U8(10), U8(11), U8(12)]

    with pytest.raises(ValueError, match="cannot change"):
        matrix.values[0][1:2] = [1, 2]
    with pytest.raises(OverflowError):
        matrix.values[0] = [1, 2, 256]


def test_owned_fam_supports_list_like_length_changes() -> None:
    packet = _Packet(tail=[1, 2])
    view = packet.tail
    static_size = ctypes.sizeof(_Packet)

    view.append(3)
    view.extend([4, 5])
    view.insert(1, 9)
    assert list(view) == [U16(1), U16(9), U16(2), U16(3), U16(4), U16(5)]
    assert ctypes.sizeof(packet) == static_size + 6 * ctypes.sizeof(ctypes.c_uint16)

    assert view.pop() == U16(5)
    del view[1:3]
    view[1:2] = [7, 8]
    assert list(packet.tail) == [U16(1), U16(7), U16(8), U16(4)]

    view.clear()
    assert list(view) == []
    assert ctypes.sizeof(packet) == static_size


def test_existing_fixed_and_fam_views_follow_an_owned_reallocation() -> None:
    packet = _Packet(data=[1, 2, 3], tail=[4])
    fixed = packet.data
    tail = packet.tail

    # A sufficiently large growth normally moves ctypes' allocation.  Views
    # resolve the parent address on each operation rather than caching it.
    tail.extend(range(100))

    assert list(fixed) == [U8(1), U8(2), U8(3)]
    assert list(tail) == [U16(4), *(U16(value) for value in range(100))]
    fixed[0] = 8
    assert packet.data[0] == U8(8)


def test_held_static_child_tracks_parent_reallocation() -> None:
    parent = _StaticChildParent(child=_Static(value=1), dynamic=[1])
    child = parent.child

    parent.dynamic.extend(range(100))
    child.value = 99

    assert child.value == U32(99)
    assert parent.child.value == U32(99)


def test_pointer_context_temporarily_pins_owned_fam_storage() -> None:
    packet = _Packet(tail=[1])
    pointer = pointer_to(packet)

    with pointer:
        with pytest.raises(BufferError, match="pinned"):
            packet.tail.append(2)

        # Context management is deliberately reentrant.  The outer context
        # must keep the allocation pinned after the inner context exits.
        with pointer:
            with pytest.raises(BufferError, match="pinned"):
                packet.tail.clear()

        with pytest.raises(BufferError, match="pinned"):
            packet.tail.extend([2, 3])

    packet.tail.append(2)
    assert list(packet.tail) == [U16(1), U16(2)]


def test_record_memoryview_pins_storage_until_release() -> None:
    packet = _Packet(tail=[1])
    view = memoryview(packet)

    assert view.nbytes == ctypes.sizeof(packet)
    with pytest.raises(BufferError, match="pinned"):
        packet.tail.append(2)

    view.release()
    packet.tail.append(2)
    assert list(packet.tail) == [U16(1), U16(2)]


def test_nested_record_memoryview_pins_the_root_record() -> None:
    parent = _DynamicParent(
        prefix=1,
        child=_DynamicChild(tag=2, payload=[3]),
    )
    child = parent.child
    view = memoryview(child)

    with pytest.raises(BufferError, match="pinned"):
        parent.child.payload.append(4)

    view.release()
    child.payload.append(4)
    assert list(parent.child.payload) == [U8(3), U8(4)]


def test_array_buffer_pins_the_root_record_until_release() -> None:
    packet = _Packet(data=[1, 2, 3], tail=[4])
    view = packet.data.buffer

    assert bytes(view) == bytes((1, 2, 3))
    with pytest.raises(BufferError, match="pinned"):
        packet.tail.extend([5, 6])

    view.release()
    packet.tail.extend([5, 6])
    assert list(packet.tail) == [U16(4), U16(5), U16(6)]


def test_from_buffer_consumes_one_exact_record_and_borrows_storage() -> None:
    static_size = ctypes.sizeof(_Packet)
    storage = bytearray(5 + static_size + 2 * ctypes.sizeof(ctypes.c_uint16))
    packet = _Packet.from_buffer(storage, 5)

    assert len(packet.tail) == 2
    packet.count = 0x11223344
    packet.tail[:] = [7, 8]
    assert storage[5:9] == bytes(ctypes.c_uint32(0x11223344))
    assert list(packet.tail) == [U16(7), U16(8)]

    with pytest.raises(BufferError, match="cannot be resized"):
        packet.tail.append(9)
    with pytest.raises(BufferError, match="cannot be resized"):
        packet.tail.clear()
    with pytest.raises(TypeError, match="writable"):
        _Packet.from_buffer(bytes(static_size))


def test_static_from_buffer_is_also_exact_and_copy_is_owned() -> None:
    size = ctypes.sizeof(_Static)

    with pytest.raises(ValueError, match="expected exactly"):
        _Static.from_buffer(bytearray(size + 1))

    original = _Packet(tail=[1, 2, 3])
    duplicate = _Packet.from_buffer_copy(bytes(original))
    duplicate.tail.append(4)

    assert list(original.tail) == [U16(1), U16(2), U16(3)]
    assert list(duplicate.tail) == [U16(1), U16(2), U16(3), U16(4)]


def test_from_address_is_rejected_only_for_dynamic_records() -> None:
    static = _Static(value=7)
    alias = _Static.from_address(ctypes.addressof(static))
    alias.value = 8
    assert static.value == U32(8)

    with pytest.raises(TypeError, match="cannot infer"):
        _Packet.from_address(ctypes.addressof(static))

    with pytest.raises(TypeError, match="not bool"):
        _Static.from_address(cast(Any, True))
    with pytest.raises(OverflowError, match="native pointer range"):
        _Static.from_address(-1)
    with pytest.raises(OverflowError, match="native pointer range"):
        _Static.from_address(1 << (ctypes.sizeof(ctypes.c_void_p) * 8))


def test_dynamic_tail_can_be_nested_and_held_views_follow_parent_resize() -> None:
    parent = _DynamicParent(
        prefix=1,
        child=_DynamicChild(tag=2, payload=[3, 4]),
    )
    child = parent.child
    held_payload = child.payload
    separately_obtained_child = parent.child

    child.payload.append(5)

    assert parent.prefix == U16(1)
    assert parent.child.tag == U16(2)
    assert list(held_payload) == [U8(3), U8(4), U8(5)]
    assert list(separately_obtained_child.payload) == [U8(3), U8(4), U8(5)]


def test_union_can_model_alternative_dynamic_tail_interpretations() -> None:
    union = _TailUnion(bytes_=[1, 2, 3, 4])
    assert list(union.bytes_) == [U8(1), U8(2), U8(3), U8(4)]
    assert list(union.words) == [
        U16(ctypes.c_uint16.from_buffer_copy(b"\x01\x02").value),
        U16(ctypes.c_uint16.from_buffer_copy(b"\x03\x04").value),
    ]

    container = _UnionContainer(prefix=9, tail=union)
    held = container.tail
    held.words = [0x0202, 0x0303, 0x0404]

    assert container.prefix == U16(9)
    assert list(container.tail.words) == [U16(0x0202), U16(0x0303), U16(0x0404)]
    expected_bytes = bytes(
        (ctypes.c_uint16 * 3)(0x0202, 0x0303, 0x0404)
    )
    assert list(held.bytes_) == [U8(value) for value in expected_bytes]

    with pytest.raises(TypeError, match="at most one"):
        _TailUnion(bytes_=[1], words=[2])


def test_pointer_fields_retain_owned_sequence_and_string_backing() -> None:
    record = _PointerRecord(values=[1, 2, 3], text="hello")

    assert record.values.known_length == 3
    assert [record.values[index] for index in range(3)] == [U8(1), U8(2), U8(3)]
    assert record.text.known_length == 6
    assert ctypes.string_at(cast(Any, record.text)) == b"hello"

    # Re-reading reconstructs the rich pointer using the record's owner
    # sidecar, rather than degrading it to an unbounded raw-address pointer.
    assert record.values.known_length == 3
    assert record.text.known_length == 6


def test_pointer_array_elements_recursively_retain_owner_provenance() -> None:
    fixed = Pointer[U8]([1, 2])
    nested = Pointer[U8]([3, 4])
    dynamic = Pointer[U8]([5, 6])
    fixed_backing = cast(Any, fixed)._ctypesx_owner
    nested_backing = cast(Any, nested)._ctypesx_owner
    dynamic_backing = cast(Any, dynamic)._ctypesx_owner
    references = (
        weakref.ref(fixed_backing),
        weakref.ref(nested_backing),
        weakref.ref(dynamic_backing),
    )

    def increment(value: int) -> int:
        return value + 1

    record = _PointerArrays(
        fixed=[fixed],
        nested=[[nested]],
        callbacks=[cast(Any, increment)],
        dynamic=[dynamic],
    )
    del fixed, nested, dynamic
    del fixed_backing, nested_backing, dynamic_backing
    gc.collect()

    assert all(reference() is not None for reference in references)
    assert record.fixed[0].known_length == 2
    assert record.fixed[0][1] == U8(2)
    assert record.nested[0][0].known_length == 2
    assert record.nested[0][0][1] == U8(4)
    assert record.dynamic[0].known_length == 2
    assert record.dynamic[0][1] == U8(6)
    assert cast(Any, record.callbacks[0])(41) == 42

    # Both direct element replacement and a FAM relocation must update or
    # preserve the recursive sidecars.
    record.fixed[0] = [11, 12]
    record.nested[0][0] = [7, 8, 9]
    record.dynamic[0] = [13, 14]
    record.dynamic.extend([[10]] * 100)

    assert record.fixed[0].known_length == 2
    assert record.fixed[0][1] == U8(12)
    assert record.nested[0][0].known_length == 3
    assert record.nested[0][0][2] == U8(9)
    assert record.dynamic[0].known_length == 2
    assert record.dynamic[0][1] == U8(14)


def test_record_array_elements_retain_nested_pointer_owners() -> None:
    fixed = _PointerElement(values=[1, 2])
    dynamic = _PointerElement(values=[3, 4])
    record = _RecordElementArrays(fixed=[fixed], dynamic=[dynamic])
    held_dynamic = record.dynamic[0]
    del fixed, dynamic
    gc.collect()

    assert record.fixed[0].values.known_length == 2
    assert record.fixed[0].values[1] == U8(2)
    assert record.dynamic[0].values.known_length == 2
    assert record.dynamic[0].values[1] == U8(4)

    record.dynamic.extend(
        _PointerElement(values=[index]) for index in range(100)
    )
    held_dynamic.values = [8, 9, 10]

    assert held_dynamic.values.known_length == 3
    assert held_dynamic.values[2] == U8(10)
    assert record.dynamic[0].values.known_length == 3
    assert record.dynamic[0].values[2] == U8(10)


def test_external_pointer_overwrite_invalidates_owner_provenance() -> None:
    record = _PointerRecord(values=[1, 2], text="hello")
    values_offset = field_info(_PointerRecord, "values").offset
    ctypes.c_void_p.from_address(
        ctypes.addressof(record) + values_offset
    ).value = 0

    assert record.values.is_null
    assert record.values.known_length is None
