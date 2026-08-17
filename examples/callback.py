"""Runnable typed callback example."""

from typing import assert_type

from ctypesx import FunctionPointer, U8


UnaryOperation = FunctionPointer[[U8], U8]


def increment(value: U8) -> U8:
    return U8(value + 1)


callback = UnaryOperation(increment)
assert_type(callback(U8(3)), U8)
assert callback(U8(3)) == U8(4)
