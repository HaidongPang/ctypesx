# Ownership and safety

ctypesx adds validation and lifetime tracking around memory it understands. It
does not turn the C memory model into managed Python memory and cannot make an
arbitrary address safe.

Read this page before exposing a pointer, callback, memoryview, or resizable
record to foreign code.

## Terms

- **Owned record:** storage created by a normal constructor or
  `from_buffer_copy`. ctypesx may resize a dynamic owned record.
- **Borrowed record:** storage created by `from_buffer` or static
  `from_address`. The external owner controls its lifetime; ctypesx cannot
  resize it.
- **Owned pointer buffer:** native storage created by converting a Python
  sequence or string. The pointer retains the backing object.
- **View:** a record field, array, FAM, or span that resolves another object's
  storage rather than owning independent bytes.
- **Owner sidecar:** Python metadata associated with checked record assignments
  to retain pointer/string/callback backing objects.
- **Pin:** a temporary or field-lifetime prohibition on moving an owned dynamic
  record while an address is exported.

## Ownership matrix

| Operation | Copies bytes? | Borrows storage? | Preserves managed owners? | Resizable FAM? |
|---|---:|---:|---:|---:|
| `Record(...)` | initializes owned storage | no | checked field assignments retain owners | yes |
| `Record.from_buffer(...)` | no | yes | existing pointer bits have no inferred owners | no |
| `Record.from_buffer_copy(...)` | yes | no | no; bytes do not encode sidecars | yes |
| `bytes(record)` | yes | no | no | not applicable to copy |
| `memoryview(record)` | no | yes | keeps record alive and pinned | resize blocked while view lives |
| `Pointer[T](sequence)` | yes, element conversion | no | pointer owns native array | fixed pointer buffer |
| `pointer_to(record)` | no | yes | pointer retains record and tracks relocation | context pins during use |
| raw integer pointer/address | no | yes, unverifiable | no | no tracking |

## Dynamic records and relocation

A list-like FAM may require a larger native allocation. Existing checked nested
record, `Array`, and `FamArray` views follow the root record's current address.
Raw native addresses cannot.

ctypesx pins the root allocation while it knows an address is actively exported
through:

- `memoryview(record)`;
- `memoryview(array_view)` or `array_view.buffer`;
- an active managed pointer or `VoidPointer` context; or
- a record-backed pointer stored through a checked ctypesx record field.

A length-changing FAM operation while pinned raises `BufferError`. Equal-length
updates remain possible.

These exports are tracked because they pass through ctypesx. The following do
not pin:

- `ctypes.addressof(record)`;
- `ctypes.byref(record)` or `ctypes.pointer(record)`;
- an integer `.address` after the property returns; a typed record-backed
  pointer may also hold stale pre-relocation bits until its context refreshes;
- `Array.raw`; and
- pointers/casts created directly through raw ctypes.

Never retain one of those untracked addresses across a possible FAM resize.

## Pointer and callback sidecars

When a checked record descriptor receives a managed pointer, string, callback,
or an array/record containing those values, ctypesx stores owner entries beside
the raw record bytes. Re-reading the field recovers the rich value and keeps its
backing objects alive.

Sidecars are Python state. They are not present in the C object representation.
Consequences:

- `bytes(record)` copies address bits but not pointee ownership;
- `from_buffer_copy(bytes(record))` cannot reconstruct owners;
- `ctypes.memmove` and external C writes do not create or transfer owners;
- a buffer borrowed from another producer may contain pointers whose lifetimes
  are entirely external; and
- serializing a pointer-bearing record never makes its target portable.

Use a byte copy of a pointer-bearing record only when the native contract and
the application separately guarantee every pointee lifetime.

## External overwrites

Raw ctypes or C code may overwrite an owner-bearing ABI field that still has a
Python sidecar. This includes typed/string/void pointers, callbacks, and nested
owner-bearing elements. On the next checked field read, ctypesx compares the
current bytes with the committed fingerprint. If they differ, it drops stale
metadata and returns a value reconstructed from the raw ABI bits.

Until that synchronization read, the former owner may remain conservatively
retained or pinned. This can delay a resize, but avoids exposing stale ownership
through the checked field API.

Do not use raw descriptors or `memmove` to mutate FAM extents or
owner-bearing fields when an ordinary ctypesx assignment can express the
operation.

## Never call `ctypes.resize` on a ctypesx record

`ctypes.resize(record, size)` is inherited and is not intercepted. It changes
ctypes storage without updating ctypesx's extent, nested-view, owner, or pin
bookkeeping. The resulting object can have inconsistent invariants and unsafe
views.

Use `FamArray` list operations to resize owned records. Borrowed records are
deliberately non-resizable.

## Foreign retention contracts

A pointer context pins a record only for the Python `with` block:

```python
with pointer_to(record) as pointer:
    foreign_call(pointer)
```

If `foreign_call` stores `pointer`, the external lifetime continues after the
block. The application must keep the owner alive and block relocation until C
releases the address. There is no automatic way for ctypesx to observe that
release.

The same rule applies to callbacks passed to C: keep the function-pointer
object alive as long as native code might call it.

## Constness

`ConstPointer` and `ConstSpan` block writes through the checked Python
interfaces. They express API intent and improve static checking.

They do not provide read-only pages or stop:

- foreign code from writing;
- a mutable alias from writing; or
- raw ctypes casts and descriptors from writing.

Treat constness as a checked-view property, not a security boundary.

## Raw addresses

Address-taking APIs reject `bool`, negative values, and integers wider than the
host pointer width. They cannot check:

- whether a page is mapped;
- alignment for the pointee type;
- allocation size or element count;
- read/write/execute permission;
- object lifetime; or
- concurrent mutation by foreign code.

An invalid dereference or function call can crash Python instead of raising an
exception. Isolate truly untrusted native input in another process; no ctypes
wrapper can make it memory-safe in-process.

## Callback safety

Catch every Python exception inside a C callback and translate it to the ABI's
documented error representation. Argument conversion happens before the user
callable and result conversion happens after it, so those failures cannot be
caught inside the callable. Use open scalar arguments for untrusted enum-like
input and construct/validate the final semantic result before returning. The
current wrapper has no generic conversion-error policy.

Every pointer-valued callback invocation appends a retention token until the
callback object is destroyed, even if the same external pointer is returned
repeatedly. Automatically owned results also retain their full backing storage.
This prevents use-after-free when C keeps earlier results, but token count and,
for new owned buffers, backing memory can grow without bound. Prefer externally
managed buffers when the ABI defines a different lifetime.

If a returned pointer is derived from a dynamic record, its retained token pins
that record until the callback is destroyed. Every FAM length change during that
period raises `BufferError`.

## Concurrency

Dynamic type caches, record layout registries, FAM relocation, and sidecar
updates are not synchronized for free-threaded CPython. Free-threaded builds are
not currently supported.

With the normal GIL build, foreign code can still access memory concurrently
while Python is not executing. The binding author must enforce the native API's
threading and mutation protocol. ctypesx does not add locks to ABI memory.

## Error categories

- `TypeError`: wrong input category, unsupported declaration, const violation,
  or operation unavailable for that record category.
- `ValueError`: structurally valid category with invalid shape or semantic
  value, such as the wrong fixed-array length.
- `OverflowError`: number, address, allocation size, or bit pattern outside its
  representable range.
- `BufferError`: requested resize or view operation conflicts with borrowed,
  pinned, or shortened backing storage.
- `IndexError`: bounded `Array`, `FamArray`, or `Span` access is outside the
  logical extent.

Native memory faults are outside this exception model and may terminate the
process.
