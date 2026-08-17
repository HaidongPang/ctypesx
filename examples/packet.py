"""Runnable version of the README quick-start example."""

from typing import Annotated

from ctypesx import (
    Array,
    Bits,
    CBool,
    CStruct,
    ConstCharPointer,
    FamArray,
    Field,
    Length,
    U8,
    U16,
)


class Packet(CStruct):
    ready: CBool = Field()
    mode: Annotated[U8, Bits(3)] = Field()
    ports: Annotated[Array[U16], Length(2)] = Field()
    name: ConstCharPointer = Field()
    payload: FamArray[U8] = Field()


packet = Packet(
    ready=1,
    mode=5,
    ports=[8000, 8001],
    name="console",
    payload=[1, 2, 3],
)

packet.payload.append(4)
packet.ports[0] = 9000

assert packet.ready == CBool(True)
assert packet.ports[0] == U16(9000)
assert list(packet.payload) == [U8(1), U8(2), U8(3), U8(4)]
