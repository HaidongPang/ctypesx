# Pointers and strings

ctypesx pointer classes are real ctypes pointer types with a semantic pointee,
checked Python conversion, and explicit ownership metadata.

## Typed pointers

Create mutable or Python-read-only pointer types with generics:

```python
import ctypes

from ctypesx import ConstPointer, Pointer, U8


BytePointer = Pointer[U8]
ReadOnlyBytePointer = ConstPointer[U8]

assert BytePointer is Pointer[U8]  # generated types are cached
assert issubclass(BytePointer, ctypes.POINTER(ctypes.c_uint8))
```

`Pointer` and `ConstPointer` are factories, not usable bare ABI types. Always
parameterize them before construction or placing them in a signature. Bare
factory construction is outside the supported API even if Python permits an
implementation object to be created.

`Pointer[T]` and `ConstPointer[T]` accept:

- another compatible ctypesx pointer;
- `None` or integer address 0 for a null pointer;
- a nonzero native-width integer raw address; or
- a `collections.abc.Sequence` of elements, converted into a new owned C-array
  snapshot.

```python
pointer = Pointer[U8]([1, 2, 3])

assert pointer.known_length == 3
assert pointer[1] == U8(2)
pointer[1] = 9
```

A generator, general iterable, `memoryview`, string, or bytes object is not a
generic sequence input. String pointer types have separate conversions
described below.

Sequence construction snapshots values; later mutation of the original Python
container does not change the C buffer. An empty sequence produces an owned,
non-NULL allocation with `known_length == 0`, which is distinct from `None`.

## Integer input always means address

This distinction is critical:

```python
from ctypesx import pointer_to


Pointer[U8](7)       # raw address 0x7; unsafe to dereference
Pointer[U8]([7])     # owned one-element C array
pointer_to(7, U8)    # owned C scalar initialized to 7
pointer_to(U8(7))    # pointee type inferred from the semantic value
```

Address conversion rejects `bool`, negative values, and values wider than
`uintptr_t`. It cannot determine whether a nonzero address is mapped, aligned,
live, large enough, or safe. Dereferencing an invalid pointer can terminate the
process.

## Pointer properties and indexing

Managed pointers expose:

- `.address`: the pointer object's currently stored integer address, or 0 for
  NULL;
- `.known_length`: owned/derived element-count metadata or `None`;
- `.is_null`: whether the pointer is NULL; and
- `.is_const`: whether checked writes are disabled.

`known_length` is not a bounds check. `pointer[index]` follows raw C pointer
arithmetic and does not consult it. Negative pointer indexes access memory
before the address; they are not Python-container negative indexing. Use
[`Span[T]`](spans.md) for checked indexing and slicing.

Only the ctypesx `pointer[index]` path performs semantic conversion. Inherited
raw ctypes surfaces such as `.contents`, `ctypes.cast`, and direct native writes
can bypass conversion, constness, bounds metadata, and ownership bookkeeping.

A pointer derived from a relocatable record can still contain the address from
before the most recent FAM move. Outside `with pointer:`, neither `.address` nor
direct pointer indexing refreshes it. Do not inspect or dereference a dynamic
record-backed pointer outside its context. `Span` operations and
`VoidPointer.address` enter the managed context internally; a typed
`Pointer.address` deliberately remains a cheap view of its stored ABI bits.

## Const pointers

`ConstPointer[T]` can be built from a compatible mutable or const pointer.
Converting a const pointer back to `Pointer[T]` is rejected because it removes
qualification.

Checked assignment through a const pointer raises `TypeError`:

```python
readonly = ConstPointer[U8]([1, 2])
# readonly[0] = 3  # TypeError
```

This is a Python API guarantee, not memory protection and not a C type-system
enforcement mechanism. Foreign C, an aliasing mutable pointer, or raw ctypes
operations can still modify the same storage.

## Character pointers

Use the named string pointer types:

| C intent | ctypesx type | Extra accepted Python inputs |
|---|---|---|
| `char *` | `CharPointer` | ASCII `str`, `bytes`, `bytearray` |
| `const char *` | `ConstCharPointer` | same, plus mutable `CharPointer` |
| `wchar_t *` | `WCharPointer` | `str` |
| `const wchar_t *` | `ConstWCharPointer` | `str`, plus mutable `WCharPointer` |

```python
from ctypesx import ConstCharPointer, WCharPointer


name = ConstCharPointer("console")
wide = WCharPointer("guest")
```

String construction creates new owned native storage and appends a terminating
NUL. `.known_length` includes that terminator. Embedded NULs are rejected.
`str` input for a char pointer must be entirely ASCII; raw `bytes` or
`bytearray` may contain arbitrary nonzero byte values. `bytearray` is copied,
not borrowed.

These types model pointers to element storage, not the special automatic
`bytes` conversion behavior of `ctypes.c_char_p`. Indexing a char pointer reads
one-byte `bytes` elements; indexing a wide pointer reads `str` elements.

## `VoidPointer`

`VoidPointer` is a checked `ctypes.c_void_p` subclass. It accepts:

- `None` or a native integer address;
- `Pointer[T]` or `ConstPointer[T]`; and
- `Span[T]` or `ConstSpan[T]`.

Erasing a managed typed pointer preserves its Python owner and any dynamic
record relocation metadata:

```python
from ctypesx import VoidPointer


typed = Pointer[U8]([1, 2, 3])
erased = VoidPointer(typed)
assert not erased.is_null
```

There is no checked dereference operation for `void *`. Cast it to a concrete
typed pointer only when the native contract establishes the pointee type and
extent.

## `pointer_to()`

`pointer_to(value, pointee=None)` creates a typed pointer to one existing or
converted value.

The pointee can be inferred for:

- ctypesx scalars, enums, records, generated pointer-compatible values;
- `CStruct` and `CUnion` instances; and
- ctypes arrays.

Plain Python values require an explicit pointee because an integer alone would
otherwise be ambiguous:

```python
from ctypesx import CChar, U32


count_pointer = pointer_to(10, U32)
char_pointer = pointer_to("A", CChar)
```

For a scalar, conversion creates an owned native scalar. For a record,
`pointer_to(record)` refers to the existing record storage. For a ctypes array,
it refers to the existing array and records its length.

## Dynamic-record pointers and context management

A record containing a FAM may move when its tail changes. A pointer derived
from that record refreshes its address and pins the allocation while used as a
context manager:

```python
with pointer_to(dynamic_record) as pointer:
    foreign_function(pointer)
```

Within the block, the pointer is refreshed after the allocation is pinned, and
a length-changing FAM operation raises `BufferError`. Context management is
reentrant.

The context only describes its active Python lifetime. If foreign code retains
the pointer, keeping the record alive is insufficient: keep the context itself
active until the native release, or use fixed/non-resizable backing. One pattern
is an `ExitStack` held by the registration object:

```python
from contextlib import ExitStack


exports = ExitStack()
pointer = exports.enter_context(pointer_to(dynamic_record))
foreign_register(pointer)

# ... C may use pointer while exports remains open ...

foreign_unregister(pointer)
exports.close()
```

After the context closes, C must not use a saved address. ctypesx cannot observe
a foreign retention contract.

`VoidPointer` preserves the same context behavior when created from a
record-backed typed pointer.

## Pointer fields and owner sidecars

Assigning an owned sequence, string, callback, or pointer through a ctypesx
record descriptor retains the relevant backing object in a sidecar. Re-reading
the field reconstructs the rich pointer, including `known_length`, instead of
degrading it to address bits.

A record-backed pointer stored in another ctypesx record pins its target for
the field's lifetime. Replacing the field or releasing the containing record
removes that managed export.

Raw ctypes or foreign code can overwrite an owner-bearing ABI field without
updating its sidecar. This applies to typed/string/void pointers, callbacks, and
nested elements. ctypesx detects a byte fingerprint change on the next checked
field read and invalidates stale ownership metadata. Until that read, the
previous target may remain conservatively retained or pinned.

Byte copies, `memmove`, and external C writes transfer only pointer bits, never
the sidecar. See [Ownership and safety](ownership-and-safety.md).
