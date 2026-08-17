# ctypesx

`ctypesx` is a typed, checked, and declarative layer over Python's standard
[`ctypes`](https://docs.python.org/3.14/library/ctypes.html) module. It lets a
supported C data model be declared once with normal Python annotations while
preserving native C layout, useful runtime validation, and precise static
field types.

The project grew out of the infrastructure built for
[`kvm-abi`](https://github.com/HaidongPang/kvm-abi), a Python representation of
the Linux KVM UAPI inspired by the
[`rust-vmm/kvm`](https://github.com/rust-vmm/kvm) ecosystem. `ctypesx` extracts
the reusable, KVM-independent ctypes enhancements from that work.

> **Status:** the source version is the unreleased `0.1.0`; project maturity is
> experimental and the public API may change before the first stable release.

## Why ctypesx?

`ctypes` is an excellent FFI runtime, but its declarations do not preserve
domain-specific Python types and many conversions follow C-style truncation or
raw-pointer semantics. `ctypesx` keeps ctypes as the ABI engine and adds a
checked Python-facing model.

| Capability | `ctypes` | `ctypesx` |
|---|---|---|
| Record declaration | `_fields_` tuples containing strings and ctypes types | annotations plus `Field()` |
| Field read type | commonly plain `int`, `float`, or `bytes` | exact `U8`, enum, pointer, record, or array-view type |
| Integer overflow | may truncate or wrap during ctypes conversion | rejected by default; explicit `wrap()` is available |
| Constructor checking | little useful static information | keyword names and input types checked by Pyright |
| Enum storage | modeled separately from the C field | enum/flag carries an explicit C integer representation |
| Flexible array members | manual allocation, address arithmetic, and `resize` | checked, list-like resizing for owned `FamArray[T]`; fixed extent when borrowed |
| Pointer ownership | mostly implicit ctypes `_objects` behavior | owned snapshots, owner sidecars, relocation tracking, and pins |
| Pointer plus length | hand-written pair | bounded `Span[T]` and `ConstSpan[T]` views |
| Generation or compilation | none | none |

The same annotation is consumed by the runtime record compiler and by the
static type checker. There is no `.pyi` mirror, stub generator, C extension,
or import-time source generation.

## Requirements and installation

- CPython 3.14 or newer;
- the host-native ABI exposed by that Python build; and
- no runtime dependencies outside the standard library.

Until a PyPI release exists, install directly from Git:

```console
python -m pip install "git+https://github.com/HaidongPang/ctypesx.git"
```

or with uv:

```console
uv add "ctypesx @ git+https://github.com/HaidongPang/ctypesx.git"
```

For development:

```console
git clone https://github.com/HaidongPang/ctypesx.git
cd ctypesx
uv sync
```

## Quick start

Suppose a native header contains this host-ABI structure:

```c
struct packet {
    _Bool ready;
    unsigned char mode : 3;
    uint16_t ports[2];
    const char *name;
    uint8_t payload[];
};
```

The corresponding ctypesx declaration is ordinary, type-checkable Python:

```python
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
```

Fields appear in physical C order. Constructors are keyword-only, omitted
fields are zero-initialized, and unknown keywords are rejected. Numeric range,
bit width, array length, and FAM placement are checked instead of silently
approximated.

The complete runnable version lives in
[`examples/packet.py`](https://github.com/HaidongPang/ctypesx/blob/main/examples/packet.py).

## ctypes remains the FFI runtime

`ctypesx` does not replace `ctypes.CDLL`, `PyDLL`, symbol lookup, or the complete
ctypes API.

`CStruct`, `CUnion`, generated `Pointer[T]` types, `VoidPointer`, and generated
`FunctionPointer` types are real ctypes ABI classes. In contrast, scalar and
enum types such as `U32` and `Mode` are Python semantic value classes carrying
C storage metadata; they are not ctypes `_SimpleCData` classes. A normal
foreign-function prototype must therefore keep using ctypes scalar classes:

```python
import ctypes

from ctypesx import CInt, Pointer, U32, pointer_to


# library.consume.argtypes = [ctypes.c_uint32, Pointer[Packet]]
# library.consume.restype = ctypes.c_int
with pointer_to(packet) as packet_pointer:
    # raw_result = library.consume(U32(4), packet_pointer)
    # result = CInt(raw_result)
    pass
```

See [ctypes interoperability](https://github.com/HaidongPang/ctypesx/blob/main/docs/ctypes-interop.md)
for the exact boundary and
[the migration guide](https://github.com/HaidongPang/ctypesx/blob/main/docs/migration-from-ctypes.md) for before/after
examples.

## Core capabilities

- checked native and fixed-width C scalars, including explicit wrap and
  bit-pattern operations;
- closed enums and bounded flags with an explicit C integer representation;
- annotation-defined structures, unions, nested records, arrays, and
  bit-fields;
- owned and borrowed flexible array members with list-like mutation;
- typed mutable and const pointers, ASCII and wide string pointers, and
  `void *`;
- typed fixed-arity C callbacks;
- bounded mutable/read-only pointer views through `Span` and `ConstSpan`;
- exact buffer extent checks, zero-copy borrowed records, and pin-aware
  `memoryview` exports;
- pointer, string, and callback backing-storage retention across checked field
  assignments; and
- inline typing with a `py.typed` marker, tested under strict Pyright.

## Safety model in one minute

`ctypesx` can validate representations and track memory it owns. It cannot
make an arbitrary native address safe.

- A nonzero integer passed to a pointer type is always a raw address.
- `Pointer[T].known_length` is ownership metadata, not a bounds check; use
  `Span[T]` when a length matters.
- `ConstPointer` and `ConstSpan` prevent writes through checked Python APIs,
  but foreign C and raw ctypes casts can still write to the memory.
- A sequence or string passed to a pointer creates an owned C-buffer snapshot;
  it does not borrow the original Python container.
- `memoryview(record)` and tracked pointer contexts pin a relocatable FAM
  allocation. A length-changing operation then raises `BufferError`.
- `ctypes.addressof`, `byref`, `pointer`, `cast`, `memmove`, `resize`, raw
  descriptors, and integer addresses bypass some or all ctypesx bookkeeping.
- Copying record bytes copies pointer bits, not the owner sidecars that keep
  pointees alive.
- Dynamic/FAM records must be passed to C by pointer, never by value.

Read [ownership and safety](https://github.com/HaidongPang/ctypesx/blob/main/docs/ownership-and-safety.md)
before exchanging
owned pointers or resizable records with foreign code.

## Documentation

- [Documentation home](https://github.com/HaidongPang/ctypesx/blob/main/docs/index.md)
- [Getting started](https://github.com/HaidongPang/ctypesx/blob/main/docs/getting-started.md)
- [Migrating from ctypes](https://github.com/HaidongPang/ctypesx/blob/main/docs/migration-from-ctypes.md)
- [Scalars](https://github.com/HaidongPang/ctypesx/blob/main/docs/scalars.md)
- [Enums and flags](https://github.com/HaidongPang/ctypesx/blob/main/docs/enums-and-flags.md)
- [Structures and unions](https://github.com/HaidongPang/ctypesx/blob/main/docs/records.md)
- [Arrays, bit-fields, and FAMs](https://github.com/HaidongPang/ctypesx/blob/main/docs/arrays-and-fam.md)
- [Pointers and strings](https://github.com/HaidongPang/ctypesx/blob/main/docs/pointers-and-strings.md)
- [Callbacks](https://github.com/HaidongPang/ctypesx/blob/main/docs/callbacks.md)
- [Span and ConstSpan](https://github.com/HaidongPang/ctypesx/blob/main/docs/spans.md)
- [ctypes interoperability](https://github.com/HaidongPang/ctypesx/blob/main/docs/ctypes-interop.md)
- [Ownership and safety](https://github.com/HaidongPang/ctypesx/blob/main/docs/ownership-and-safety.md)
- [Static typing](https://github.com/HaidongPang/ctypesx/blob/main/docs/typing.md)
- [Layout and portability](https://github.com/HaidongPang/ctypesx/blob/main/docs/layout-and-portability.md)
- [Performance and copy model](https://github.com/HaidongPang/ctypesx/blob/main/docs/performance.md)
- [Public API index](https://github.com/HaidongPang/ctypesx/blob/main/docs/api-reference.md)
- [Current limitations](https://github.com/HaidongPang/ctypesx/blob/main/docs/limitations.md)
- [Development guide](https://github.com/HaidongPang/ctypesx/blob/main/docs/development.md)

## Scope and current limitations

`ctypesx` is not a C header parser, binding generator, portable serialization
format, or cross-target layout engine. Layout follows the running Python
process.

The current record compiler intentionally does not implement packed or custom
layout, non-native byte order, forward/incomplete/self-referential records,
concrete-record inheritance, anonymous-union flattening, unnamed or zero-width
bit-fields, or variadic/Windows-specific callback conventions. Free-threaded
CPython is not currently supported.

These and other precise boundaries are listed in
[`docs/limitations.md`](https://github.com/HaidongPang/ctypesx/blob/main/docs/limitations.md).

## Development and contributing

```console
uv sync
uv run pytest
uv run pyright
uv build
```

Runtime tests, runnable examples, local documentation links, Python-fence
syntax, and `typing_tests/` are part of the required verification. See
[CONTRIBUTING.md](https://github.com/HaidongPang/ctypesx/blob/main/CONTRIBUTING.md)
before submitting a change and
[CHANGELOG.md](https://github.com/HaidongPang/ctypesx/blob/main/CHANGELOG.md) for
release notes.

## License

`ctypesx` is licensed under the
[MIT License](https://github.com/HaidongPang/ctypesx/blob/main/LICENSE).
