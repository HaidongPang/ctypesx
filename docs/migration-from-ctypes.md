# Migrating from ctypes

This guide migrates an existing hand-written ctypes binding to ctypesx while
preserving its native ABI. It also explains which parts should continue using
the standard library.

Migration is not a global replacement of `import ctypes`. ctypes remains the
library loader and general FFI runtime; ctypesx replaces the data-declaration
and Python-facing value layer where its checked model applies.

## Contents

- [Boundary and behavior changes](#1-understand-the-boundary-first)
- [Scalar mapping](#4-map-scalar-types)
- [Structures, unions, arrays, and bit-fields](#5-migrate-a-structure)
- [Enums and masks](#8-migrate-enums-and-masks)
- [Pointers, strings, spans, and callbacks](#9-migrate-pointers)
- [Flexible array members](#12-migrate-a-flexible-array-member)
- [Buffer parsing and CDLL integration](#13-migrate-buffer-parsing)
- [Gradual migration](#15-plan-a-gradual-migration)
- [Layout verification](#16-verify-compatibility)
- [Migration checklist](#migration-checklist)

## 1. Understand the boundary first

Keep using ctypes for:

- `CDLL`, `PyDLL`, and platform loaders;
- symbol lookup and ordinary `argtypes`/`restype` configuration;
- raw scalar storage types in normal foreign-function prototypes;
- APIs outside ctypesx's model, including variadic calls and platform-specific
  calling conventions; and
- deliberately low-level casts, string reads, and memory operations.

Use ctypesx for:

- checked scalar and enum values;
- annotation-defined records and unions;
- typed fixed arrays, bit-fields, and list-like FAMs;
- managed typed, string, void, and function pointers;
- bounded pointer views; and
- static constructor/field checking.

`CStruct`, `CUnion`, generated pointer classes, `VoidPointer`, and generated
function-pointer classes are real ctypes ABI types. `U32`, `CInt`, `Mode`, and
other scalar/enum classes are Python semantic values, not ctypes
`_SimpleCData` classes.

Therefore this is invalid:

```python
# function.argtypes = [U32]
# function.restype = CInt
```

Keep raw scalar prototypes and wrap returned values:

```python
import ctypes

from ctypesx import CInt, U32


# function.argtypes = [ctypes.c_uint32]
# function.restype = ctypes.c_int
# result = CInt(function(U32(7)))
```

## 2. Main behavior changes

| Existing ctypes behavior | ctypesx behavior |
|---|---|
| record fields declared in `_fields_` | annotations in physical order plus `Field()` |
| constructors commonly accept positional values | keyword-only; omitted fields zero-initialize |
| scalar reads commonly produce plain Python primitives | reads preserve `U8`, enum, pointer, and other semantic types |
| integer conversion may truncate/wrap | ordinary conversion raises `OverflowError`; `wrap()` is explicit |
| enum type stored separately from field storage | enum/flag owns an explicit storage representation |
| arrays exposed as raw ctypes arrays | checked, zero-copy `Array[T]` views |
| FAM allocation uses manual size/address arithmetic | owned `FamArray[T]` grows and shrinks like a list |
| pointer plus length managed by convention | optional bounded `Span[T]`/`ConstSpan[T]` view |
| pointer backing often relies on `_objects` details | checked assignments retain owner sidecars and track relocation |
| `from_buffer` accepts any sufficiently large buffer | selected range must be exactly one record |
| raw ctypes operations are the primary path | raw operations remain available but may bypass ctypesx invariants |

## 3. Establish a layout baseline

Before rewriting declarations, record the old layout and compare it with the
real C header on every supported target:

```python
import ctypes


def snapshot_layout(record_type: type[ctypes.Structure]) -> tuple[int, int]:
    return ctypes.sizeof(record_type), ctypes.alignment(record_type)
```

A test that only compares old ctypes with new ctypesx can catch migration
regressions, but cannot prove that either declaration matches C. Build a small
C layout probe from the authoritative header; see
[Layout and portability](layout-and-portability.md).

## 4. Map scalar types

| ctypes | ctypesx | Notes |
|---|---|---|
| `c_bool` | `CBool` | accepts `bool`, 0, or 1 only |
| `c_char` | `CChar` | reads as numeric 0..255; accepts one ASCII `str`, one `bytes`, or integer |
| `c_wchar` | `CWChar` | exactly one host `wchar_t` character |
| `c_byte` / `c_ubyte` | `CSChar` / `CUChar` | C signed/unsigned char |
| `c_short` / `c_ushort` | `CShort` / `CUShort` | host C width |
| `c_int` / `c_uint` | `CInt` / `CUInt` | host C width |
| `c_long` / `c_ulong` | `CLong` / `CULong` | host ABI width |
| `c_longlong` / `c_ulonglong` | `CLongLong` / `CULongLong` | host ABI width |
| `c_int8` ... `c_int64` | `S8` ... `S64` | exact signed widths |
| `c_uint8` ... `c_uint64` | `U8` ... `U64` | exact unsigned widths |
| `c_size_t` / `c_ssize_t` | `CSize` / `CSSize` | host C typedef widths |
| pointer-sized signed/unsigned | `CIntPtr` / `CUIntPtr` | host pointer width |
| `c_float` / `c_double` / `c_longdouble` | `CFloat` / `CDouble` / `CLongDouble` | native precision quantization |
| optional C complex ctypes | corresponding `C*Complex` | feature depends on Python/libffi build |

The ctypesx scalar itself is the Python value; it does not have the usual
`ctypes.c_uint32(...).value` wrapper shape:

```python
from ctypesx import U8


value = U8(10)
assert isinstance(value, int)
assert type(value) is U8
```

Arithmetic usually returns a plain Python number and is validated again when
constructed or assigned:

```python
result = U8(250) + 10
assert type(result) is int
U8(result)  # OverflowError
```

If old code intentionally depends on C truncation, make it explicit:

```python
assert U8.wrap(256) == U8(0)
```

## 5. Migrate a structure

Given this C declaration:

```c
struct header {
    uint16_t kind;
    uint8_t flags;
    uint16_t ports[2];
};
```

The ctypes version might be:

```python
class OldHeader(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint16),
        ("flags", ctypes.c_uint8),
        ("ports", ctypes.c_uint16 * 2),
    ]


old = OldHeader(1, 3, (ctypes.c_uint16 * 2)(8000, 8001))
```

The ctypesx version is:

```python
from typing import Annotated

from ctypesx import Array, CStruct, Field, Length, U8, U16


class Header(CStruct):
    kind: U16 = Field()
    flags: U8 = Field()
    ports: Annotated[Array[U16], Length(2)] = Field()


header = Header(
    kind=1,
    flags=3,
    ports=[8000, 8001],
)
```

Important changes:

- annotations, not `_fields_` tuple order, define physical order;
- every field needs `Field()`;
- construction is keyword-only;
- every field may be omitted and is then zero-initialized;
- unknown keywords fail immediately;
- field reads preserve exact semantic types;
- scalar overflow is rejected;
- array assignment requires the exact length; and
- the class fails to build if a declaration is unsupported.

## 6. Migrate nested records and unions

Nested ctypesx records use their Python class directly:

```python
class Request(CStruct):
    header: Header = Field()
    sequence: U16 = Field()


request = Request(
    header=Header(kind=1, flags=0, ports=[80, 443]),
    sequence=9,
)
```

The runtime can also construct a nested static record from a mapping. The
generated static constructor signature expects `Header`, so strict Pyright code
should use an explicit instance as shown.

Migrate a union by replacing `ctypes.Union` and `_fields_` with `CUnion` and
annotations:

```python
from ctypesx import CUnion, U32


class Value(CUnion):
    bits: U32 = Field()
    code: U32 = Field()


value = Value(bits=0x1234)
```

A `CUnion` constructor accepts at most one field. Anonymous union flattening is
not supported; give the union a field name in its containing record.

## 7. Migrate arrays and bit-fields

Old ctypes:

```python
class Old(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_uint8, 3),
        ("matrix", (ctypes.c_uint8 * 4) * 2),
    ]
```

ctypesx:

```python
from ctypesx import Bits


class New(CStruct):
    mode: Annotated[U8, Bits(3)] = Field()
    matrix: Annotated[
        Array[Array[U8]],
        Length(2, 4),
    ] = Field()
```

`Length` dimensions are outermost-first. `Array` is a field view and cannot be
created directly. It provides checked element access and equal-length slice
assignment.

Bit-field width is checked at class creation and values are checked at
assignment. Bit-field allocation remains host ABI dependent; validate against C
and pass bit-field records by pointer.

## 8. Migrate enums and masks

ctypes usually combines a standalone `IntEnum` with an integer record field:

```python
from enum import IntEnum


class OldMode(IntEnum):
    OFF = 0
    ON = 1


class OldControl(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_uint16)]
```

ctypesx carries the C width on the enum:

```python
from ctypesx import U16Enum, U32Flag


class Mode(U16Enum):
    OFF = 0
    ON = 1


class Feature(U32Flag):
    READ = 1
    WRITE = 2


class Control(CStruct):
    mode: Mode = Field()
    features: Feature = Field()
```

Choose carefully:

- an enum rejects every undeclared numeric value;
- a flag retains unknown bits that fit its storage; and
- a scalar is preferable for an open numeric namespace or forward-compatible
  numeric values.

Prefer fixed-underlying bases such as `U16Enum` for the strongest `.value`
static type.

## 9. Migrate pointers

Old ctypes:

```python
buffer = (ctypes.c_uint8 * 3)(1, 2, 3)
old_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8))
```

ctypesx:

```python
from ctypesx import ConstPointer, Pointer, pointer_to


pointer = Pointer[U8]([1, 2, 3])
readonly = ConstPointer[U8](pointer)
```

Sequence input creates an owned C-array snapshot. `Pointer[T]` retains that
backing storage. `ConstPointer[T]` blocks checked Python writes but does not
stop foreign C or raw ctypes from modifying the memory.

Integer input always means an address:

```python
Pointer[U8](7)       # address 0x7, not value 7
Pointer[U8]([7])     # owned one-element array
pointer_to(7, U8)    # owned mutable C scalar copy
pointer_to(U8(7))    # same, with inferred pointee type
```

`Pointer.known_length` is metadata, not a bounds check. Raw pointer indexing
still performs unchecked C pointer arithmetic. Replace pointer-plus-count helper
code with `Span[T]` inside Python:

```python
from ctypesx import Span


view = Span[U8](pointer)
assert view[-1] == U8(3)
```

A span is not an ABI type. Pass its pointer and length separately, and keep the
pointer context active for the complete native access:

```python
with view.pointer as span_pointer:
    foreign_function(span_pointer, len(view))
```

## 10. Migrate string and void pointers

| ctypes intent | ctypesx |
|---|---|
| mutable `char *` | `CharPointer` |
| `const char *` | `ConstCharPointer` |
| mutable `wchar_t *` | `WCharPointer` |
| `const wchar_t *` | `ConstWCharPointer` |
| `void *` | `VoidPointer` |

Char-pointer `str` input is ASCII-only. String conversion creates an owned
NUL-terminated buffer and rejects embedded NUL. `bytes` can carry arbitrary
nonzero raw byte values. Wide strings use the host `wchar_t` representation.

Unlike `ctypes.c_char_p`, these are modeled as typed element pointers with
managed backing storage. Use `ctypes.string_at` explicitly when the native
contract establishes a valid NUL-terminated address.

`VoidPointer` accepts typed pointers and spans while preserving known Python
ownership and dynamic-record relocation metadata. It has no dereference API.

## 11. Migrate callbacks

Old ctypes:

```python
OldCallback = ctypes.CFUNCTYPE(
    ctypes.c_uint8,
    ctypes.c_uint8,
)
```

ctypesx:

```python
from ctypesx import FunctionPointer


Callback = FunctionPointer[[U8], U8]


def increment(value: U8) -> U8:
    return U8(value + 1)


callback = Callback(increment)
```

The callback receives and returns semantic types. Function pointer invocation
is fixed-arity and positional. `None` as a signature result means C `void`.

Keep the callback object alive for the full foreign lifetime. Catch Python
exceptions inside the callback and convert them into the ABI's documented error
result.

Every pointer-result invocation retains a token until the callback is destroyed.
Automatically owned results also retain their backing buffers. This protects
earlier addresses but grows token metadata on every such call and can accumulate
substantial memory when each call creates a new buffer.

Raw ctypes types are accepted in a `FunctionPointer` signature at runtime, but
raw scalar arguments/results follow normal ctypes primitive conversion and the
generic static signature cannot represent that projection exactly. Prefer
ctypesx semantic types for checked callbacks, or retain `ctypes.CFUNCTYPE` for
an intentionally raw callback.

## 12. Migrate a flexible array member

Old ctypes often uses a zero-length field, manual resize, and address
arithmetic:

```python
class OldMessage(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("data", ctypes.c_uint8 * 0),
    ]


count = 3
old_message = OldMessage(count=count)
ctypes.resize(old_message, ctypes.sizeof(OldMessage) + count)
old_tail = (ctypes.c_uint8 * count).from_address(
    ctypes.addressof(old_message) + OldMessage.data.offset
)
old_tail[:] = [1, 2, 3]
```

ctypesx:

```python
from ctypesx import FamArray


class Message(CStruct):
    count: U32 = Field()
    data: FamArray[U8] = Field()


message = Message(count=3, data=[1, 2, 3])
message.data.append(4)
message.count = len(message.data)
```

Important changes:

- `FamArray` must be the final field and a direct FAM must follow a named
  prefix field;
- owned instances resize automatically through list-like operations;
- the separate count field is not synchronized automatically;
- `ctypes.sizeof(Message)` is the static prefix size;
- `ctypes.sizeof(message)` is the current complete instance extent;
- borrowed `from_buffer` instances allow only equal-length changes;
- dynamic records reject `from_address` because an address has no extent;
- pinning exports cause length-changing operations to raise `BufferError`; and
- `ctypes.resize(message, ...)` is inherited and not intercepted. Calling it
  directly can split ctypes' allocation size from ctypesx's logical extent,
  owners, and views; it must never be used on a ctypesx record.

Pass dynamic records to C only by pointer:

```python
with pointer_to(message) as message_pointer:
    foreign_function(message_pointer)
```

If C retains that address, keeping the record or pointer object alive is not
enough: the pin context itself must remain active until C releases the address,
or the backing must be fixed/non-resizable. A registration API can keep an
`ExitStack` open across register/use/unregister and close it only after the
native release.

## 13. Migrate buffer parsing

Both libraries expose `from_buffer` and `from_buffer_copy`, but ctypesx chooses
strict message boundaries.

From the supplied offset to the end of the selected buffer there must be exactly
one record. A larger receive or transport buffer must be sliced first:

```python
start = 16
message_size = 64
frame = memoryview(receive_buffer)[start : start + message_size]
message = Message.from_buffer(frame)
```

`from_buffer` requires writable storage and borrows it. The extent is fixed.
`from_buffer_copy` accepts readable storage, creates an owned copy, and permits
future FAM resizing.

For a static record, even one extra byte is rejected. For a dynamic record, the
extent must end on a valid FAM element boundary.

Byte copies do not preserve pointer or callback owner sidecars. A copied record
containing addresses needs an independent lifetime plan for every pointee.

## 14. Configure `CDLL` functions

Continue using ctypes scalar classes in normal prototypes and ctypesx
record/pointer classes where they are real ctypes types:

```python
import ctypes

from ctypesx import CInt, Pointer


# library = ctypes.CDLL("libdevice.so")
# library.submit.argtypes = [
#     ctypes.c_uint32,
#     Pointer[Message],
# ]
# library.submit.restype = ctypes.c_int

# with pointer_to(message) as pointer:
#     status = CInt(
#         library.submit(U32(ctypes.sizeof(message)), pointer)
#     )
```

Do not place `U32` or `CInt` themselves in `argtypes`/`restype`. A semantic
numeric value can still be passed because it is a Python numeric subclass, and a
raw return can be wrapped to regain the exact type and validation.

`Span` also cannot appear in a prototype; split it into its pointer and length.

## 15. Plan a gradual migration

Use a complete record declaration as the minimum migration unit. A ctypesx
record field cannot mix raw ctypes scalar or ordinary ctypes record annotations:

```python
class Invalid(CStruct):
    # value: ctypes.c_uint32 = Field()   # unsupported
    # legacy: OldHeader = Field()       # unsupported
    pass
```

Recommended order:

1. Build native layout probes and freeze current byte-layout tests.
2. Introduce semantic scalars, enums, and flags at Python API boundaries.
3. Migrate static leaf records with no pointers or FAMs.
4. Migrate parents that embed those leaves.
5. Migrate arrays, unions, and bit-fields.
6. Migrate pointer and callback fields with explicit lifetime tests.
7. Migrate FAM records and every buffer boundary.
8. Enable strict Pyright checks for constructor and field usage.
9. Repeat native layout tests on each target.

The reverse nesting direction can help temporarily for pointer/callback-free
static leaf records because a ctypesx record is a real ctypes class:

```python
class NewLeaf(CStruct):
    value: U32 = Field()


class OldParent(ctypes.Structure):
    _fields_ = [("leaf", NewLeaf)]
```

Do not embed a dynamic ctypesx record by value in a legacy container. The legacy
type sees only the static prefix and has no relocation state. A legacy parent
also cannot reproduce ctypesx owner sidecars for pointer/callback fields, even
when ctypes' internal `_objects` happens to retain a backing object.

`Pointer[OldCtypesRecord]` can be used at pointer boundaries, so records need not
all migrate in one release.

Do not store `pointer_to(dynamic_record)` in an ordinary legacy ctypes field and
assume ctypes ownership is enough. The legacy field does not establish a
ctypesx pin, so a later FAM resize can stale its address. Keep a managed pointer
context active for the complete native use or migrate the containing field to a
ctypesx record descriptor.

## 16. Verify compatibility

Compare static shape:

```python
from ctypesx import field_info


def assert_compatible(
    old: type[ctypes.Structure],
    new: type[CStruct],
    field_names: tuple[str, ...],
) -> None:
    assert ctypes.sizeof(old) == ctypes.sizeof(new)
    assert ctypes.alignment(old) == ctypes.alignment(new)
    for name in field_names:
        assert getattr(old, name).offset == field_info(new, name).offset
```

Compare representative native object bytes:

```python
assert bytes(old_value) == bytes(new_value)
```

Exceptions and caveats:

- pointer bytes differ when allocations differ;
- padding must be initialized consistently;
- bit-fields require a C helper because `offsetof` is unavailable;
- class size and several instance extents must be tested for FAM records; and
- the real C header/toolchain, not the old Python declaration, is authoritative.

## 17. Replace unsafe assumptions

Audit old code for:

- implicit integer truncation;
- positional structure construction;
- buffers larger than the parsed record;
- `ctypes.resize` and tail address arithmetic;
- pointers retained without a Python owner;
- `POINTER(T)` indexing that assumes a hidden length;
- `c_char_p` automatic bytes behavior;
- raw `memmove` into pointer/callback fields;
- `byref`/`addressof` addresses retained across a resize; and
- callbacks that let Python exceptions escape.

The migration is incomplete until each occurrence is either expressed through
the checked API or explicitly documented as an unsafe native boundary.

## 18. Declarations that cannot migrate directly yet

The current record compiler does not support:

- `_pack_`, `_align_`, `_layout_`, or non-native byte order;
- forward, incomplete, or self-referential record declarations;
- concrete record inheritance;
- anonymous-union flattening;
- unnamed or zero-width bit-fields;
- dynamic records used as array elements;
- `from_address` for dynamic records;
- variadic/Windows-specific/error-state callback variants; or
- free-threaded CPython.

Keep the relevant declaration in raw ctypes, isolate it behind a pointer
boundary, or postpone migration. Never approximate an unsupported layout.

## Migration checklist

- [ ] The original layout is verified against a compiled C probe.
- [ ] Every migrated field uses a ctypesx semantic type and `Field()`.
- [ ] Constructor call sites use keyword arguments.
- [ ] Intentional truncation uses `wrap()` explicitly.
- [ ] Unsigned bit-pattern reinterpretation uses `from_bits()` only after the
      pattern is known to fit the storage width.
- [ ] Enum versus flag versus open scalar semantics are chosen deliberately.
- [ ] Fixed arrays have exact `Length` metadata and assignment tests.
- [ ] Bit-fields are validated per target and passed by pointer.
- [ ] Every pointer/string/callback has a documented owner and lifetime.
- [ ] Raw pointer-plus-length loops use a span where appropriate.
- [ ] Dynamic records use `FamArray`, not `ctypes.resize`.
- [ ] Count/capacity fields are updated explicitly by ABI-specific code.
- [ ] `from_buffer` callers slice an exact record extent.
- [ ] Byte copies of pointer-bearing records do not assume copied ownership.
- [ ] `CDLL` scalar prototypes still use raw ctypes storage classes.
- [ ] Dynamic records cross the C boundary only through a pinned pointer.
- [ ] Every relevant Python owner and pin outlives the foreign pointer/callback
      retention period.
- [ ] Runtime tests, strict Pyright, and native layout probes all pass.

For the underlying rules, continue with [Ownership and safety](ownership-and-safety.md),
[ctypes interoperability](ctypes-interop.md), and
[Current limitations](limitations.md).
