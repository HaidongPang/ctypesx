# Arrays, bit-fields, and flexible array members

ctypesx represents fixed C arrays and flexible tails as typed, zero-copy Python
views returned by record fields.

## Fixed arrays

Annotate a fixed C array with `Array[T]` and one `Length` declaration:

```python
from typing import Annotated

from ctypesx import Array, CStruct, Field, Length, U8


class Digest(CStruct):
    bytes_: Annotated[Array[U8], Length(32)] = Field()
```

`Length` dimensions are outermost-first. Nested arrays repeat `Array` in the
annotation:

```python
class Matrix(CStruct):
    cells: Annotated[
        Array[Array[U8]],
        Length(2, 4),
    ] = Field()
```

This corresponds to a C field whose shape is `[2][4]`.

`Array` cannot be constructed directly by application code. It needs a record
storage provider and is created when the field is read. For standalone bounded
contiguous memory, use [Span](spans.md).

## Array operations

An `Array[T]` is mutable and fixed length:

```python
matrix = Matrix(cells=[[1, 2, 3, 4], [5, 6, 7, 8]])

assert matrix.cells[0][2] == U8(3)
matrix.cells[1][0] = 9
matrix.cells[0][:] = [10, 11, 12, 13]
```

Supported behavior:

- `len(view)`, iteration, negative indexing, and slicing;
- element assignment with the declared type's conversion;
- slice assignment only when the resulting length is unchanged;
- `bytes(view)` for a copy of the current bytes;
- `.buffer` or `memoryview(view)` for a pinned writable byte view;
- `.raw` for the unchecked current ctypes array; and
- `.address` for the unpinned current first-byte address.

The implementation converts all slice inputs before committing any byte. A bad
element therefore raises without partially updating the array.

`.raw` and `.address` are unsafe across an owning FAM resize. Existing checked
`Array` views themselves remain valid because they resolve the current parent
address on every operation.

## Bit-fields

Declare a bit-field with `typing.Annotated` and `Bits(width)`:

```python
from ctypesx import Bits, S8


class Status(CStruct):
    mode: Annotated[U8, Bits(3)] = Field()
    delta: Annotated[S8, Bits(4)] = Field()
```

The storage type must use a ctypes integer/boolean field representation and the
width must be positive and no wider than that storage. `CInteger` types,
integer-backed enums/flags, and `CBool` are supported; `CChar` uses the distinct
ctypes `char` representation and is not a bit-field storage type. Assignment is
checked against the signed or unsigned range represented by the bit width:

- `mode` accepts `0..7`;
- `delta` accepts `-8..7`.

Bit-field allocation order and by-value calling conventions are host ABI and
compiler dependent. Following ctypes portability constraints, pass records
containing bit-fields to foreign functions by pointer. Validate the resulting
layout against a C probe built for every supported target.

Unnamed and zero-width bit-fields are not supported.

## Flexible array members

A `FamArray[T]` is the final dynamic field of a structure:

```python
from ctypesx import FamArray, U16, U32


class Message(CStruct):
    count: U32 = Field()
    words: FamArray[U16] = Field()


message = Message(count=2, words=[10, 20])
```

The record compiler enforces:

- at most one dynamic tail;
- the dynamic tail is the final field;
- a direct FAM follows at least one named field;
- its element is a supported static non-array C value with nonzero size; and
- the FAM offset equals the static `sizeof` of the record.

The last condition rejects host layouts with ambiguous trailing padding rather
than counting padding bytes as elements.

An array-of-fixed-arrays flexible tail such as `FamArray[Array[U8]]` is not
currently expressible because the inner array has no place to declare its
`Length`. Model it manually at an unsafe boundary or keep that declaration in
raw ctypes until nested FAM element shapes are supported.

## List-like mutation

Owned records resize automatically:

```python
message.words.append(30)
message.words.extend([40, 50])
message.words.insert(1, 15)
last = message.words.pop()
del message.words[1:3]
message.words[1:2] = [60, 70]
message.words.clear()
```

`FamArray` supports indexing, iteration, slices, element assignment,
length-changing slice assignment, deletion, `append`, `extend`, `insert`,
`pop`, and `clear`.

These operations are list-like semantically, not in asymptotic complexity.
Every length change currently rebuilds and stages the complete tail, so one
change is generally O(n) and repeated single-element append can be O(n²). Use a
bulk assignment or `extend` for known batches. See
[Performance and copy model](performance.md).

All replacement elements are converted before allocation contents are
committed. If conversion or allocation fails, the original logical contents
remain intact.

The count or size fields commonly found before a C FAM are not updated
automatically:

```python
message.words.extend([1, 2])
message.count = len(message.words)
```

ctypesx cannot infer whether an ABI count means elements, bytes, capacity, or
something else.

## Owned and borrowed extents

An ordinary constructor or `from_buffer_copy` creates an owned record. Its FAM
may change length unless the allocation is pinned.

`from_buffer` creates a borrowed record whose external extent is fixed. It
allows element assignment and equal-length replacements, but rejects every
length-changing operation with `BufferError`.

```python
storage = bytearray(bytes(Message(count=2, words=[1, 2])))
borrowed = Message.from_buffer(storage)
borrowed.words[:] = [3, 4]
# borrowed.words.append(5)  # BufferError
```

The buffer from the chosen offset to its end is treated as exactly one record.
Slice a larger transport buffer before calling `from_buffer`.

## Size and relocation

For a dynamic record:

```python
static_size = ctypes.sizeof(Message)
instance_size = ctypes.sizeof(message)

assert instance_size == static_size + len(message.words) * ctypes.sizeof(ctypes.c_uint16)
```

A length change may move the owning allocation. Held checked record, array, and
FAM views track the new location. Raw integer addresses, `.raw` arrays,
`ctypes.addressof`, `byref`, and raw ctypes pointers do not.

`memoryview(record)`, `memoryview(array_view)`, an active managed pointer
context, or a managed record pointer field pins the root allocation. Resizing
while pinned raises `BufferError` rather than invalidating an exported address.

Do not call `ctypes.resize(record)` directly. It bypasses ctypesx extent,
owner, and pin bookkeeping.

## Nested dynamic tails and unions

ctypesx extends the direct ISO C FAM model in two useful ways:

- a final nested `CStruct` may carry the dynamic tail; and
- a final explicit `CUnion` may provide alternative FAM interpretations.

```python
from ctypesx import CUnion


class Tail(CUnion):
    bytes_: FamArray[U8] = Field()
    words: FamArray[U16] = Field()


class Container(CStruct):
    tag: U16 = Field()
    tail: Tail = Field()
```

These forms model existing ABIs, but are ctypesx dynamic-tail extensions, not
literal ISO C declarations of multiple FAMs. Every union view interprets the
same bytes. The current extent may be valid for one element width but not
another; accessing an incompatible interpretation raises `BufferError`.

Changing an interpretation or its length remains the caller's responsibility.
A dynamic-tail record cannot be an `Array` or `FamArray` element, although it
may be the final nested field of a containing structure.

Dynamic/FAM records must be passed to C by pointer. A C by-value call follows
the static type size and cannot transfer an arbitrary Python-managed tail.
