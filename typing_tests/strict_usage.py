"""Static assertions for the public annotation-driven API."""

from __future__ import annotations

from typing import Annotated, assert_type

from ctypesx.array import Array, FamArray
from ctypesx.field import Bits, Field, Length
from ctypesx.pointer import ConstCharPointer, ConstPointer, Pointer
from ctypesx.records import CStruct
from ctypesx.scalar import CBool, CChar, U8, U16


class Packet(CStruct):
    ready: CBool = Field()
    tag: CChar = Field()
    value: U8 = Field()
    mode: Annotated[U8, Bits(3)] = Field()
    fixed: Annotated[Array[U16], Length(2)] = Field()
    data: FamArray[U8] = Field()


empty = Packet()
packet = Packet(
    ready=1,
    tag="A",
    value=128,
    mode=7,
    fixed=[1, 2],
    data=[3, 4, 5],
)

assert_type(packet.ready, CBool)
assert_type(packet.tag, CChar)
assert_type(packet.value, U8)
assert_type(packet.fixed, Array[U16])
assert_type(packet.data, FamArray[U8])

packet.value = 1
packet.fixed = [2, 3]
packet.data = [4, 5]
packet.data.append(6)

Packet(value=object())  # pyright: ignore[reportArgumentType]
Packet(fixed=[object()])  # pyright: ignore[reportArgumentType]
Packet(data=[object()])  # pyright: ignore[reportArgumentType]
packet.value = object()  # pyright: ignore[reportAttributeAccessIssue]
packet.data = [object()]  # pyright: ignore[reportAttributeAccessIssue]
Packet(True)  # pyright: ignore[reportCallIssue]


class PointerPacket(CStruct):
    values: Pointer[U8] = Field()
    name: ConstPointer[CChar] = Field()


pointer_packet = PointerPacket(values=[1, 2, 3], name="ascii")
pointer_packet.values = 0x1234
pointer_packet.name = "name"
assert_type(pointer_packet.values, Pointer[U8])
assert_type(pointer_packet.name, ConstPointer[CChar])

PointerPacket(values=[object()])  # pyright: ignore[reportArgumentType]
pointer_packet.values = [object()]  # pyright: ignore[reportAttributeAccessIssue]


class TextPacket(CStruct):
    text: ConstCharPointer = Field()


text_packet = TextPacket(text="hello")
text_packet.text = b"world"
assert_type(text_packet.text, ConstCharPointer)
