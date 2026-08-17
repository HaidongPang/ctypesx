# Getting started

This guide defines a small native record, constructs it from ordinary Python
values, inspects its C layout, and shares it with a writable buffer.

## Install

ctypesx requires CPython 3.14 or newer. It is not yet published on PyPI, so
install it from Git:

```console
python -m pip install "git+https://github.com/HaidongPang/ctypesx.git"
```

For a checkout used during development:

```console
git clone https://github.com/HaidongPang/ctypesx.git
cd ctypesx
uv sync
```

No compiler, binding generator, or runtime dependency is required.

## Define a record

Imagine this C declaration:

```c
struct message {
    uint16_t kind;
    uint8_t flags;
    uint8_t data[4];
};
```

Declare the same host-ABI shape with annotations:

```python
from typing import Annotated

from ctypesx import Array, CStruct, Field, Length, U8, U16


class Message(CStruct):
    kind: U16 = Field()
    flags: U8 = Field()
    data: Annotated[Array[U8], Length(4)] = Field()
```

The annotation order is the physical field order. Every C field must have a
`Field()` marker. Class creation fails immediately for unsupported field types,
invalid array dimensions, oversized bit-fields, or an invalid flexible tail.

## Construct and mutate it

Constructors are keyword-only. Every field is optional and omitted bytes are
zero-initialized:

```python
message = Message(kind=3, data=[10, 20, 30, 40])

assert message.kind == U16(3)
assert message.flags == U8(0)
assert list(message.data) == [U8(10), U8(20), U8(30), U8(40)]

message.flags = 5
message.data[1] = 99
```

Assignment performs the same conversion as construction. `message.kind =
70000` raises `OverflowError`; assigning three elements to `data` raises
`ValueError`. Conversion of a whole array or slice is staged before bytes are
changed, so a failing element does not leave a partially updated field.

## Inspect the native layout

Records are real `ctypes.Structure` or `ctypes.Union` subclasses:

```python
import ctypes

from ctypesx import field_info


assert issubclass(Message, ctypes.Structure)
print(ctypes.sizeof(Message))
print(ctypes.alignment(Message))

info = field_info(Message, "data")
print(info.offset, info.size, info.ctype)
```

`field_info()` is preferred to depending on generated raw descriptors. It
reports the field offset, byte size, C storage type, bit metadata, and whether
the field is itself a direct `FamArray` field. A final nested record or union may
carry a dynamic tail even though that containing field is not marked flexible.

`bytes(message)` returns a copy of the complete current native object
representation, including padding and host byte order:

```python
wire_copy = bytes(message)
assert len(wire_copy) == ctypes.sizeof(message)
```

This is appropriate only when the consumer expects exactly the same host ABI;
it is not a portable serialization format.

## Borrow or copy a buffer

`from_buffer` borrows writable storage without copying. Unlike the standard
ctypes method, ctypesx requires the selected range to contain exactly one
record:

```python
storage = bytearray(ctypes.sizeof(Message))
borrowed = Message.from_buffer(storage)
borrowed.kind = 0x1234

assert storage[:2] == bytes(ctypes.c_uint16(0x1234))
```

If the transport buffer contains several objects or framing bytes, slice it
first:

```python
frame = memoryview(storage)[0 : ctypes.sizeof(Message)]
borrowed = Message.from_buffer(frame)
```

`from_buffer_copy` accepts readable storage and returns an independent owned
record:

```python
owned = Message.from_buffer_copy(bytes(borrowed))
owned.kind = 7
assert borrowed.kind != owned.kind
```

`from_address` is available only for static records and is an unsafe raw-address
operation. It cannot validate mapping, alignment, lifetime, or accessibility.

## Add a flexible array member

A final `FamArray[T]` turns an owned structure into a dynamically sized record:

```python
from ctypesx import FamArray, U32


class Frame(CStruct):
    count: U32 = Field()
    payload: FamArray[U8] = Field()


frame = Frame(count=2, payload=[1, 2])
frame.payload.append(3)
frame.count = len(frame.payload)

assert ctypes.sizeof(frame) == ctypes.sizeof(Frame) + 3
```

`ctypes.sizeof(Frame)` is the static C header size. `ctypes.sizeof(frame)` is
the complete current allocation, including its FAM. A separate count field is
never updated automatically because the relationship is part of the ABI's
business rules, not the C layout.

Read [Arrays, bit-fields, and FAMs](arrays-and-fam.md) before using dynamic
tails with borrowed memory or nested records.

## Pass it to foreign code

Use ctypes to load a library and configure symbols. `Message` and
`Pointer[Message]` are real ctypes ABI types:

```python
import ctypes

from ctypesx import CInt, Pointer, pointer_to


# library = ctypes.CDLL("libexample.so")
# library.consume.argtypes = [Pointer[Message]]
# library.consume.restype = ctypes.c_int
# with pointer_to(message) as pointer:
#     result = CInt(library.consume(pointer))
```

The context manager is essential for a dynamic/FAM record because it prevents
the allocation from moving during the call. If C retains the pointer after the
call, the Python owner must stay alive and pinned for that entire external
lifetime; ctypesx cannot infer it.

Scalar semantic classes such as `U8` are not valid `argtypes` or `restype`
entries. Keep using `ctypes.c_uint8` there and wrap returned values explicitly.
See [ctypes interoperability](ctypes-interop.md).

## Enable static checks

ctypesx ships inline types and `py.typed`. With Pyright in strict mode, this is
accepted:

```python
message = Message(kind=1, data=[1, 2, 3, 4])
message.kind = 2
```

while wrong names and input categories are reported before execution:

```python
Message(unknown=1)       # unknown constructor field
Message(kind=object())   # not integer-compatible
Message(data=[object()]) # invalid array element
```

Value-dependent properties such as `U8` range, ASCII content, and bit width
remain runtime checks. See [Static typing](typing.md) for the exact guarantee.

## Next steps

- [Migrate an existing ctypes binding](migration-from-ctypes.md)
- [Define enums and flags](enums-and-flags.md)
- [Use pointers and strings](pointers-and-strings.md)
- [Understand ownership and safety](ownership-and-safety.md)
