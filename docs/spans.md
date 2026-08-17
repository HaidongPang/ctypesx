# Span and ConstSpan

`Span[T]` combines a typed pointer with a Python-side element count. It offers
bounded indexing and slicing without pretending that the pair is a C ABI
record.

`ConstSpan[T]` is the read-only sibling type. It is not a subtype of mutable
`Span[T]`.

## Construction

### From a sequence

```python
from ctypesx import ConstSpan, Span, U8


data = Span[U8]([1, 2, 3])
readonly = ConstSpan[U8]([4, 5, 6])
```

The sequence becomes an owned native C-array snapshot and supplies the length.

### From a managed pointer

```python
from ctypesx import ConstPointer, Pointer


pointer = Pointer[U8]([1, 2, 3])
all_items = Span[U8](pointer)
prefix = Span[U8](pointer, 2)

const_pointer = ConstPointer[U8](pointer)
const_view = ConstSpan[U8](const_pointer)
```

If no explicit length is supplied, the pointer must have `known_length`.
An explicit length cannot exceed a known backing length.

A mutable `Span` rejects a `ConstPointer`. It also rejects construction directly
from any existing span; use `existing_span.pointer` when deliberately creating
a second mutable view. `ConstSpan` can be built from a mutable or const pointer,
`Span`, or `ConstSpan` of the same element type.

### From a raw address

```python
address = 0x12340000
view = Span[U8](address, 64)
```

A raw address always requires an explicit length. ctypesx validates only the
integer and non-negative length; it cannot validate the memory. A non-empty span
cannot use a null pointer.

## Operations

Both span types support:

- `len(span)`;
- bounded positive and negative indexing;
- slicing, returned as a Python list;
- iteration and `to_list()`;
- `.pointer`, `.address`, and `.is_const`.

Mutable spans additionally support element and equal-length slice assignment:

```python
data = Span[U8]([1, 2, 3])
data[-1] = 9
data[0:2] = [4, 5]

assert data.to_list() == [U8(4), U8(5), U8(9)]
```

Slice inputs are completely converted before any element is written. Slice
assignment cannot change a span's length. `ConstSpan` rejects every checked
write.

## Passing a span to C

A span is not a ctypes storage class and cannot appear in a `CStruct`,
`argtypes`, or `restype`. Pass its pointer and length separately:

```python
# library.consume.argtypes = [Pointer[U8], ctypes.c_size_t]
# library.consume(data.pointer, len(data))
```

For a span backed by a dynamic record, use the pointer as a context manager
during the call so the root allocation remains pinned:

```python
with data.pointer as pointer:
    foreign_function(pointer, len(data))
```

Reading `.address` or `.pointer` refreshes a record-relative address but does
not create a pin that outlives the property access.

At runtime, `Span.pointer` is always mutable and `ConstSpan.pointer` is always
const. The current inherited static annotation for mutable `Span.pointer` is the
broader `Pointer[T] | ConstPointer[T]`; strict code that passes it to an API
requiring exactly `Pointer[T]` may need `typing.cast`. This is a typing limitation
of the current release, not a runtime constness ambiguity.

## Backing changes

Span operations temporarily pin a record-backed pointer and validate its
current known extent. If another operation shortened the FAM below the span's
fixed length, later indexing, iteration, `len`, or address access raises
`BufferError` rather than reading past the new end.

An unpinned integer from `.address` can still become stale after it is returned.

## What Span does not provide

- It is not an ABI `struct { T *ptr; size_t len; }`.
- It does not implement the Python buffer protocol.
- It cannot validate an arbitrary address or prove a foreign allocation's
  lifetime.
- It does not own raw-address input.
- It cannot express capacity separately from length.

If a C API has a concrete pointer-and-length record, declare that record as a
`CStruct` and use a span only as the Python-side checked view.

## Static typing note

Index reads and writes retain the semantic element type, and `ConstSpan` is
statically non-mutable. Python's type system cannot project an arbitrary C
value type's accepted descriptor input into the direct sequence constructor of
`Span[T]`. Consequently `Span[U8]([object()])` is always rejected at runtime but
may not be rejected by Pyright. Record `Array` and `FamArray` fields do not have
this limitation.
