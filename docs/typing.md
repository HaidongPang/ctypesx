# Static typing

ctypesx uses one annotation graph for both Python's type checker and the native
record compiler. The package ships inline type information and a `py.typed`
marker; no `.pyi`, stub generation, native build, or import-time code generation
is required.

## Supported checker

The project tests Pyright in strict mode against the source, runtime tests, and
`typing_tests/`:

```toml
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.14"
```

Other type checkers may understand parts of the API, but are not currently in
the tested compatibility promise.

## Record constructors and fields

Given:

```python
from typing import Annotated

from ctypesx import Array, CStruct, FamArray, Field, Length, U8, U16


class Packet(CStruct):
    code: U8 = Field()
    fixed: Annotated[Array[U16], Length(2)] = Field()
    payload: FamArray[U8] = Field()
```

Pyright understands:

- constructor field names;
- keyword-only construction;
- each field's accepted Python input category;
- exact read types;
- checked field assignment;
- fixed-array and FAM element types; and
- array/FAM mutator input types.

```python
from typing import assert_type


packet = Packet(code=1, fixed=[2, 3], payload=[4, 5])

assert_type(packet.code, U8)
assert_type(packet.fixed, Array[U16])
assert_type(packet.payload, FamArray[U8])

packet.payload.append(6)
```

These are static errors:

```python
Packet(unknown=1)
Packet(code=object())
Packet(fixed=[object()])
packet.payload = [object()]
Packet(True)  # positional construction is forbidden
```

Every constructor field is optional because omitted C storage is
zero-initialized.

## Exact semantic result types

Fields return the declared value, enum, pointer, record, or view type rather
than a broad `int`/`Any`:

```python
from ctypesx import U8Enum


class Mode(U8Enum):
    OFF = 0
    ON = 1


class Control(CStruct):
    mode: Mode = Field()


control = Control(mode=1)
assert_type(control.mode, Mode)
assert_type(Mode.ON.value, U8)
```

Use fixed-underlying enum/flag bases such as `U8Enum` when exact static typing
of `.value` matters. The general `class Mode(CEnum, underlying=U8)` syntax is
exact at runtime but exposes `.value` as the broader `CInteger` statically.

## Pointer and callback typing

Pointer fields retain the semantic pointee:

```python
from ctypesx import ConstPointer, FunctionPointer, Pointer


type Callback = FunctionPointer[[U8], U8]


class Api(CStruct):
    values: Pointer[U8] = Field()
    readonly: ConstPointer[U8] = Field()
    callback: Callback = Field()
```

The checker distinguishes mutable and const pointers, carries callback arity
and return types, and rejects an incompatible sequence element or callable.

`pointer_to()` has precise overloads for supported ctypesx scalars and records:

```python
from ctypesx import CChar, pointer_to


assert_type(pointer_to(U8(1)), Pointer[U8])
assert_type(pointer_to(packet), Pointer[Packet])
assert_type(pointer_to("A", CChar), Pointer[CChar])
```

More dynamic raw-ctypes and pointer-to-pointer combinations may work at runtime
but can require an explicit `typing.cast` under strict analysis.

Raw ctypes scalar types in `FunctionPointer` signatures have an additional
projection gap: ctypes calls the Python callback with primitive `int`/`float`
values rather than `_SimpleCData` instances, while the generic parameter names
the ctypes class. Use ctypesx semantic scalar types for a precisely typed
callback.

## PEP 695 aliases

The runtime compiler expands PEP 695 aliases used in record fields, including
chained and generic array aliases:

```python
type Byte = U8
type ByteArray[T] = Array[T]
type Pair = Annotated[ByteArray[Byte], Length(2)]


class PairRecord(CStruct):
    values: Pair = Field()
```

The same alias is visible to Pyright. Forward, incomplete, recursive, or
unresolvable record declarations remain unsupported.

## Runtime-only validation

Static types describe accepted categories, not arbitrary value-dependent
predicates. Runtime conversion still checks:

- integer and address range;
- rejection of `bool` where ordinary integer input is expected;
- ASCII-only char-string content;
- exact string/character length;
- bit-field width;
- fixed-array runtime length;
- FAM extent and pin state; and
- whether a closed enum value is a declared member.

For example, both `U8(1)` and `U8(1000)` are statically integer-compatible, but
the latter raises `OverflowError`.

## Known static gaps

Runtime-generated pointer and function-pointer classes necessarily expose a few
dynamic constructor surfaces. Runtime conversion remains strict even where the
checker sees `Any`.

The most important known gap is direct sequence construction of `Span[T]` or
`ConstSpan[T]`. Python's type system cannot project an arbitrary C value type's
descriptor input type into that constructor. Therefore:

```python
from ctypesx import Span


Span[U8]([object()])  # runtime TypeError; not necessarily a Pyright error
```

Record `Array` and `FamArray` fields do not have this gap.

Generic `Pointer[T]` and span constructors have a separate category mismatch:
their static `Sequence` shape can admit `bytes`, `bytearray`, or `memoryview`,
while runtime generic-sequence conversion deliberately excludes those byte
containers. Use `CharPointer` for byte-string semantics or pass a normal list or
tuple of generic elements. Runtime rejection remains authoritative.

`Span.pointer` is always a mutable pointer at runtime, but its current inherited
annotation is `Pointer[T] | ConstPointer[T]`. Strict code may need to cast it to
`Pointer[T]` when calling an API whose annotation requires the exact mutable
type. `ConstSpan.pointer` has an exact `ConstPointer[T]` annotation.

Nested record assignment has a small runtime-only convenience: a mapping can be
converted into a static child record, but the generated constructor and field
type expects the child record instance. The same applies to mappings used as
static-record elements of an `Array` or `FamArray`. Construct child instances
explicitly in strict code.

## Why `Field()` is required

An annotation alone is useful to a checker but does not let the checker assign
a custom descriptor input type to each field. `Field()` is the visible marker
used by the record transform. It also separates physical C fields from unrelated
class annotations and makes unsupported declarations fail at class creation.

Conversion logic belongs to the annotated C type, not to a separate field
wrapper. A field read is still `U8`, while assignment accepts the Python inputs
declared by `U8`.
