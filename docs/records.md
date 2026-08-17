# Structures and unions

`CStruct` and `CUnion` compile Python annotations into real host-native
`ctypes.Structure` and `ctypes.Union` layouts. The annotations also remain the
source of truth for static field and constructor types.

## Declaration grammar

Every C field is an annotation followed by `Field()`:

```python
from ctypesx import CStruct, Field, U8, U32


class Header(CStruct):
    version: U8 = Field()
    length: U32 = Field()
```

Rules enforced when the class is created:

- annotation order is physical field order;
- every non-`ClassVar` field annotation requires `Field()`;
- every field type must be supported by the ctypesx record compiler;
- fixed arrays require matching `Length` metadata;
- bit-fields require one valid `Bits` width and integer storage;
- a dynamic tail must be final and unique; and
- unsupported direct `_fields_`, `_anonymous_`, `_pack_`, `_align_`, and
  `_layout_` declarations are rejected.

`ClassVar` annotations are ordinary class state and are ignored by the record
compiler.

PEP 695 type aliases, including generic array aliases, are resolved from the
same annotation graph. Forward, incomplete, recursive, or unresolved record
aliases are not supported.

## Construction and field conversion

Record construction is keyword-only. All fields are optional and storage is
zero-initialized before supplied values are assigned:

```python
header = Header(version=1)

assert header.version == U8(1)
assert header.length == U32(0)
```

An unknown keyword raises `TypeError`. Each value is converted through its
declared semantic type. A nested static record may be supplied as an existing
instance or as a mapping:

```python
class Envelope(CStruct):
    header: Header = Field()
    checksum: U32 = Field()


envelope = Envelope(header=Header(version=2, length=8))
assert envelope.header.version == U8(2)
```

The runtime also accepts a mapping for a nested static record. The generated
static constructor signature expects `Header`, however, so strict Pyright code
should construct the nested instance explicitly as above. Runtime mappings used
as static-record array/FAM elements have the same typing limitation.

Nested views share the parent's bytes. If an owning parent moves because its
final FAM grows, a previously obtained child view resolves the parent's current
address rather than continuing to use the old allocation.

## Unions

Unions use the same field syntax:

```python
from ctypesx import CUnion, S32, U32


class Word(CUnion):
    signed: S32 = Field()
    unsigned: U32 = Field()
```

A `CUnion` constructor accepts at most one field because assigning a second
field would immediately overwrite the first interpretation:

```python
word = Word(unsigned=0x1234)
```

Model an anonymous C union as an explicitly named nested `CUnion`. ctypesx does
not flatten union members into the containing record's namespace.

## Physical layout introspection

Use `field_info()` to inspect compiled layout:

```python
import ctypes

from ctypesx import FieldInfo, field_info


info = field_info(Header, "length")
assert isinstance(info, FieldInfo)
print(info.name)
print(info.python_type)
print(info.ctype)
print(info.offset, info.size)
print(info.bit_width, info.bit_offset)
print(info.flexible)

assert ctypes.sizeof(Header) >= info.offset + info.size
```

`FieldInfo` is immutable. `field_info()` avoids depending on generated raw
ctypes descriptors, which are part of the implementation rather than the
semantic API.

## Native object representation

The record itself is a ctypes object:

```python
assert issubclass(Header, ctypes.Structure)
assert issubclass(CUnion, ctypes.Union)
```

The normal ctypes operations `sizeof`, `alignment`, `addressof`, and `byref`
can see the storage. `bytes(record)` copies the complete current extent.

For a static record:

```python
assert ctypes.sizeof(header) == ctypes.sizeof(Header)
assert len(bytes(header)) == ctypes.sizeof(Header)
```

For a dynamic/FAM record, `ctypes.sizeof(RecordType)` is the static prefix but
`ctypes.sizeof(instance)` and `len(bytes(instance))` include the instance's
current tail. See [Arrays and FAMs](arrays-and-fam.md).

The byte representation contains native padding, byte order, bit-field layout,
and pointer addresses. It is an ABI object representation, not a portable
serialization format.

## Buffer constructors

### `from_buffer(buffer, offset=0, /)`

Creates a zero-copy borrowed record over writable buffer storage. The range
from `offset` to the end of the buffer must be exactly one record:

- a static record requires exactly `sizeof(RecordType)` bytes;
- a dynamic record requires at least the static prefix and must end on a valid
  FAM element boundary.

The borrowed extent cannot be resized. Equal-length field and FAM updates are
allowed.

### `from_buffer_copy(buffer, offset=0, /)`

Accepts readable storage, validates the same exact extent, and creates an
independent owned record. A copied dynamic record may resize afterward.

Copying bytes does not copy ctypesx owner sidecars for pointer or callback
fields. A copied pointer field contains only its address bits; the caller must
ensure that the pointee outlives the copy.

### `from_address(address, /)`

Available only for static records. A raw address contains no dynamic-tail
length, so dynamic records reject this operation.

Even for static records, `from_address` is unsafe. ctypesx checks only that the
integer fits the native pointer width. An unmapped, unaligned, null, or expired
address may crash the process when accessed.

## Buffer protocol and pins

`memoryview(record)` returns a writable byte view of the complete extent and
pins the root allocation until the view is released:

```python
view = memoryview(header)
try:
    assert view.nbytes == ctypes.sizeof(header)
finally:
    view.release()
```

For a dynamic record, a length-changing FAM operation while such a view exists
raises `BufferError`. A memoryview taken from a nested child pins the root
record as well.

`ctypes.addressof`, `byref`, and raw descriptors do not create a tracked pin.
See [Ownership and safety](ownership-and-safety.md).

## Inheritance and mixed ctypes fields

A concrete `CStruct` or `CUnion` cannot be extended through inheritance. Use
explicit composition so the C layout stays visible:

```python
class Extended(CStruct):
    base: Header = Field()
    extra: U32 = Field()
```

Raw ctypes scalar annotations and ordinary ctypes records are not accepted as
`CStruct` fields:

```python
class Invalid(CStruct):
    # value: ctypes.c_uint32 = Field()  # unsupported
    pass
```

Migrate a complete nested record graph from the leaves upward. Generated
ctypesx pointer and callback types support a wider raw-ctypes interoperability
surface; the record compiler intentionally remains strict.

## Field-name collisions

Fields normally use their exact C names. ctypes layout controls (`_fields_`,
`_anonymous_`, `_pack_`, `_align_`, `_layout_`, and `__slots__`) and dunder
names are reserved. Ordinary inherited API names are not: a field named
`from_buffer`, `from_buffer_copy`, or `from_address` can naturally shadow the
inherited class method. A field may also have a name such as `field_info`
because layout introspection is module-level.

Bindings that need a shadowed inherited method must choose whether preserving
the exact C spelling or retaining that convenience API is more important; the
current release has no field-alias mechanism.
