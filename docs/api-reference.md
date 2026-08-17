# Public API index

This page indexes the documented names re-exported from the `ctypesx` package
root. These names form the intended public API for the `0.1` series. Root
imports are the canonical convenience form; the following category modules are
also supported for explicit organization:

| Module | Public category |
|---|---|
| `ctypesx.scalar` | scalar value types and aliases |
| `ctypesx.enums` | enum and flag bases |
| `ctypesx.field` | `Field`, `Bits`, and `Length` |
| `ctypesx.records` | `CStruct`, `CUnion`, and field introspection |
| `ctypesx.array` | `Array` and `FamArray` |
| `ctypesx.pointer` | pointers, strings, callbacks, spans, and `pointer_to` |

Incidental module globals and private names are implementation details. The
project intentionally does not maintain a manual `__all__` list.

## Declaration metadata

### `Field() -> Any`

Marks one annotated class attribute as a physical C field. It is valid only in
a `CStruct` or `CUnion` class body. The annotated type controls conversion and
the read type.

### `Bits(width: int)`

Frozen annotation metadata for an integer bit-field. `width` must be positive
and no wider than its storage type. The normalized value is available as the
frozen `.width` attribute.

```python
mode: Annotated[U8, Bits(3)] = Field()
```

### `Length(*dimensions: int)`

Annotation metadata for nested `Array` fields. Dimensions are positive and
outermost-first and are available as the `.dimensions` tuple.

```python
values: Annotated[Array[Array[U8]], Length(2, 4)] = Field()
```

## Records

### `CStruct`

Base for annotation-defined, naturally aligned structures. It is also a
`ctypes.Structure`.

Public operations:

- `Record(**fields)` — keyword-only checked construction; omitted fields are
  zero-initialized;
- `Record.from_buffer(buffer, offset=0, /)` — exact-size writable borrowed view;
- `Record.from_buffer_copy(buffer, offset=0, /)` — exact-size owned copy;
- `Record.from_address(address, /)` — unsafe static-record borrowed view;
- `bytes(record)` — complete current native extent copy; and
- `memoryview(record)` — pinned writable byte view.

### `CUnion`

Base for annotation-defined unions and a `ctypes.Union`. It has the same buffer
operations as `CStruct`; construction accepts at most one field.

### `FieldInfo[T]`

Immutable field-layout record with attributes:

- `name: str`;
- `python_type`;
- `ctype: type`;
- `offset: int`;
- `size: int`;
- `bit_width: int | None`;
- `bit_offset: int | None`; and
- `flexible: bool` — true only when this field is itself a direct `FamArray`.

### `field_info(record_type, name, /) -> FieldInfo[Any]`

Returns physical layout metadata for one compiled record field. Unknown names
raise `KeyError`.

See [Structures and unions](records.md).

## Arrays

### `Array[T]`

Typed, zero-copy, fixed-length record-field view. Application code does not
construct it directly.

Public surface:

- `len`, iteration, integer/slice reads;
- element and equal-length slice assignment;
- `bytes(view)`;
- `.raw` — unchecked current ctypes array;
- `.address` — unpinned current first-byte address;
- `.buffer` — pinned writable byte memoryview; and
- `memoryview(view)`.

### `FamArray[T]`

List-like dynamic-tail view. It includes `Array` operations plus:

- length-changing slice assignment;
- deletion;
- `insert`, `append`, `extend`, `pop`, and `clear`.

Length changes resize an owned record and raise `BufferError` for borrowed or
pinned storage.

See [Arrays, bit-fields, and FAMs](arrays-and-fam.md).

## Integer scalars

All integer scalars derive from abstract `CInteger`, itself an `int` subclass.
They provide `BITS`, `SIGNED`, `bounds()`, `wrap()`, and `from_bits()`.

Canonical native-width types:

- `CSChar`, `CUChar`;
- `CShort`, `CUShort`;
- `CInt`, `CUInt`;
- `CLong`, `CULong`;
- `CLongLong`, `CULongLong`;
- `CSize`, `CSSize`; and
- `CIntPtr`, `CUIntPtr`.

Canonical fixed-width types:

- `S8`, `U8`;
- `S16`, `U16`;
- `S32`, `U32`; and
- `S64`, `U64`.

Aliases:

- `CSignedChar` = `CSChar`;
- `CUnsignedChar` = `CUChar`;
- `CUnsignedShort` = `CUShort`;
- `CUnsignedInt` = `CUInt`;
- `CUnsignedLong` = `CULong`;
- `CUnsignedLongLong` = `CULongLong`;
- `CInt8`, `CInt16`, `CInt32`, `CInt64` = `S8`, `S16`, `S32`, `S64`;
- `CUInt8`, `CUInt16`, `CUInt32`, `CUInt64` = `U8`, `U16`, `U32`, `U64`;
- `CSizeT`, `CSSizeT` = `CSize`, `CSSize`; and
- `CIntPtrT`, `CUIntPtrT` = `CIntPtr`, `CUIntPtr`.

## Other scalars

- `CBool` — `_Bool`, represented as an `int` subclass limited to 0/1;
- `CChar` — one raw C char byte represented as integer 0..255;
- `CWChar` — one host `wchar_t` represented as a `str` subclass;
- `CFloat`, `CDouble`, `CLongDouble` — native C floating values represented as
  `float` subclasses; and
- `CFloatComplex`, `CDoubleComplex`, `CLongDoubleComplex` — optional native C
  complex values represented as `complex` subclasses.

See [Scalars](scalars.md).

## Enums and flags

### `CEnum`

Abstract closed integer-enum base. A concrete class must specify an integer
storage with `underlying=` or inherit a fixed-underlying base.

### `CFlag`

Abstract bounded flag base using `enum.KEEP` semantics for unknown in-range
bits.

Fixed-width enum bases:

- `S8Enum`, `U8Enum`, `S16Enum`, `U16Enum`;
- `S32Enum`, `U32Enum`, `S64Enum`, `U64Enum`.

Fixed-width flag bases:

- `S8Flag`, `U8Flag`, `S16Flag`, `U16Flag`;
- `S32Flag`, `U32Flag`, `S64Flag`, `U64Flag`.

Native-width enum bases:

- `CSCharEnum`, `CUCharEnum`;
- `CShortEnum`, `CUShortEnum`;
- `CIntEnum`, `CUIntEnum`;
- `CLongEnum`, `CULongEnum`;
- `CLongLongEnum`, `CULongLongEnum`;
- `CSizeEnum`, `CSSizeEnum`; and
- `CIntPtrEnum`, `CUIntPtrEnum`.

Native-width flag bases use the same prefixes and end in `Flag`:

- `CSCharFlag`, `CUCharFlag`, `CShortFlag`, `CUShortFlag`;
- `CIntFlag`, `CUIntFlag`, `CLongFlag`, `CULongFlag`;
- `CLongLongFlag`, `CULongLongFlag`, `CSizeFlag`, `CSSizeFlag`;
- `CIntPtrFlag`, `CUIntPtrFlag`.

See [Enums and flags](enums-and-flags.md).

## Typed pointers

### `Pointer[T]`

Generated mutable ctypes pointer type. `Pointer[T](value=None, /)` accepts a
compatible managed pointer, native integer address, `Sequence` snapshot, or
`None`.

The bare `Pointer` object is a factory and must not be instantiated directly.

### `ConstPointer[T]`

Generated Python-read-only ctypes pointer type.
`ConstPointer[T](value=None, /)` also accepts a compatible mutable pointer.
Checked writes and removal of const qualification are rejected.

The bare `ConstPointer` object is a factory and must not be instantiated.

Managed pointer properties and operations:

- `.address: int` — stored pointer bits; a dynamic record-backed pointer is
  refreshed only inside its context;
- `.known_length: int | None`;
- `.is_null: bool`;
- `.is_const: bool`;
- unchecked native pointer indexing with semantic element conversion; and
- reentrant context management for dynamic-record pins.

### String pointers

- `CharPointer` and `ConstCharPointer` for `char *`;
- `WCharPointer` and `ConstWCharPointer` for `wchar_t *`.

String inputs allocate NUL-terminated owned storage.

### `VoidPointer`

Checked `void *` value accepting native addresses, managed pointers, and spans.
Provides `.address`, `.is_null`, and context management while preserving known
ownership/relocation metadata.

### `pointer_to(value, pointee=None)`

Returns an owned/retained `Pointer[T]` to one existing or converted value. Plain
Python scalars need an explicit pointee; ctypesx values, records, and ctypes
arrays can usually be inferred.

See [Pointers and strings](pointers-and-strings.md).

## Function pointers

### `FunctionPointer[[Arg1, ...], Result]`

Generates a cached fixed-arity `ctypes.CFUNCTYPE` subclass. `Result=None` means
C `void`. `Generated(value=None, /)` accepts a compatible instance, Python
callable, native integer function address, or `None`.

The bare `FunctionPointer` object is a factory and must not be instantiated.

Dynamic/FAM and bit-field records should be passed as pointer arguments.
Structures and unions are not supported as by-value callback results by the
underlying ctypes trampoline; use a pointer or out-parameter.

Generated values provide `.address`, `.is_null`, and checked positional
invocation.

See [Callbacks](callbacks.md).

## Bounded pointer views

### `Span[T]`

Mutable bounded pointer view constructed as `Span[T](source, length=None, /)`
from a sequence, compatible managed pointer, or raw address plus explicit
length.

### `ConstSpan[T]`

Read-only sibling constructed as `ConstSpan[T](source, length=None, /)`. It can
also view mutable/const pointers or other spans without exposing checked
mutation.

Common operations:

- bounded indexing and slicing;
- iteration and `to_list()`;
- `len(span)`;
- `.pointer`, `.address`, and `.is_const`.

Spans are Python views, not C ABI types and not buffer providers.

See [Span and ConstSpan](spans.md).

## Exceptions

The API uses built-in exception categories rather than defining a custom
hierarchy:

- `TypeError` for unsupported declarations/input categories and const
  violations;
- `ValueError` for invalid shapes or semantic values;
- `OverflowError` for out-of-range numeric/address/allocation values;
- `BufferError` for borrowed/pinned/shortened-storage conflicts;
- `IndexError` for bounded view indexes; and
- `NotImplementedError` when directly constructing an optional C complex value
  whose storage is unavailable; using that type in a record instead raises
  `TypeError` during class creation.
- `MemoryError` may propagate when Python or ctypes cannot allocate an owned
  array, pointer buffer, or resized record.

Invalid native memory can still fault the process outside Python's exception
model.
