# ctypes interoperability

ctypesx is a data-model extension for ctypes, not a replacement for the full
FFI runtime. Native-library loading, symbol lookup, variadic APIs, `errno`,
platform calling conventions, and general memory utilities remain the
responsibility of the standard `ctypes` module.

## Which ctypesx types are real ctypes classes?

| ctypesx category | Real ctypes ABI class? | Where it can be used directly |
|---|---:|---|
| `CStruct` subclass | yes, `ctypes.Structure` | record field in legacy ctypes, pointer pointee, compatible `argtypes` |
| `CUnion` subclass | yes, `ctypes.Union` | same categories as a ctypes union |
| `Pointer[T]`, `ConstPointer[T]` | yes, generated ctypes pointer | `argtypes`, record fields, casts |
| `CharPointer`, wide/const variants | yes, generated ctypes pointer | pointer-compatible FFI positions |
| `VoidPointer` | yes, `ctypes.c_void_p` subclass | `void *` FFI positions |
| `FunctionPointer[[...], R]` | yes, generated `CFUNCTYPE` subclass | callback fields and compatible prototypes |
| `U8`, `CInt`, `CFloat`, enum/flag | no; Python semantic value | checked Python values and ctypesx fields |
| `Array[T]`, `FamArray[T]` | no; field view | accessed from a ctypesx record |
| `Span[T]`, `ConstSpan[T]` | no; Python bounded view | Python APIs; split into pointer plus length for C |

The most common mistake is placing a semantic scalar directly in a normal
ctypes function prototype:

```python
from ctypesx import U32


# library.read.argtypes = [U32]  # invalid: U32 is not _SimpleCData
```

Keep the ctypes storage class in `argtypes` and `restype`, then explicitly wrap
the result:

```python
import ctypes


# library.read.argtypes = [ctypes.c_uint32]
# library.read.restype = ctypes.c_uint32
# result = U32(library.read(U32(7)))
```

A ctypesx numeric value is an `int`/`float` subclass, so ctypes accepts it where
the configured raw scalar type accepts a normal Python number.

## Calling a function with a record pointer

```python
import ctypes

from ctypesx import CInt, CStruct, Field, Pointer, U32, pointer_to


class Request(CStruct):
    operation: U32 = Field()
    value: U32 = Field()


# library = ctypes.CDLL("libexample.so")
# library.execute.argtypes = [Pointer[Request]]
# library.execute.restype = ctypes.c_int

request = Request(operation=1, value=42)

# with pointer_to(request) as request_pointer:
#     status = CInt(library.execute(request_pointer))
```

For a static record, the context is harmless. For a dynamic record, it refreshes
and pins relocatable storage for the call.

If the C signature accepts a structure by value, a static `CStruct` can be used
where normal ctypes supports that platform ABI. Dynamic/FAM records must never
be passed by value: the C type's static size cannot express an arbitrary
instance tail. Records containing bit-fields should also be passed by pointer
because ctypes documents by-value portability restrictions for them.

## Pointers and string parameters

Generated pointer classes can be installed directly in a prototype:

```python
from ctypesx import ConstCharPointer, Pointer, U8


# library.consume.argtypes = [Pointer[U8], ctypes.c_size_t]
# library.set_name.argtypes = [ConstCharPointer]
```

Passing a sequence or string creates owned backing storage retained by the
managed pointer for the duration of the Python object:

```python
data = Pointer[U8]([1, 2, 3])
name = ConstCharPointer("guest")

# library.consume(data, len([1, 2, 3]))
# library.set_name(name)
```

If C stores either address after returning, keep the pointer alive for the
complete native lifetime. A `Span` must be split into `span.pointer` and
`len(span)`; a span itself is not a C argument type.

## Callbacks

Use a generated `FunctionPointer` type as a callback parameter or record field:

```python
from ctypesx import FunctionPointer


Visitor = FunctionPointer[[U32], CInt]


# library.visit.argtypes = [Visitor]
```

The generated class handles semantic conversion around the underlying
`CFUNCTYPE`. Keep the callback object alive as long as foreign code may invoke
it.

Raw ctypes signature types are accepted at runtime, but callback arguments and
results then follow ctypes primitive conversion (`c_uint32` arrives as Python
`int`, for example). The current generic annotation cannot express that
projection precisely. Use ctypesx semantic types for a checked typed callback,
or retain a raw `ctypes.CFUNCTYPE` declaration when raw ctypes semantics are
intentional.

## Mixing record definitions

The ctypesx record compiler is intentionally strict. A `CStruct` field cannot
be annotated with a raw ctypes scalar or an ordinary ctypes record:

```python
class Invalid(CStruct):
    # value: ctypes.c_uint32 = Field()
    # legacy: LegacyCtypesRecord = Field()
    pass
```

Migrate a complete nested record from its leaves upward. The reverse direction
is possible for a pointer/callback-free static leaf because it is a real ctypes
class:

```python
class NewLeaf(CStruct):
    value: U32 = Field()


class LegacyParent(ctypes.Structure):
    _fields_ = [("leaf", NewLeaf)]
```

Do not embed a dynamic/FAM ctypesx record by value in a legacy ctypes container;
the legacy container knows only its static type size and none of the relocation
state. A legacy parent also does not preserve ctypesx owner sidecars for pointer
or callback fields, so those leaves must migrate together with their container
or remain behind a pointer boundary.

`Pointer[LegacyCtypesRecord]` is supported, so an integration boundary can
remain pointer-based while record declarations are migrated independently.

Storing `pointer_to(dynamic_record)` in an ordinary legacy ctypes structure does
not create a ctypesx pin. ctypes may keep the Python object alive through
`_objects`, but a later FAM relocation can still leave the ABI field stale. Use
an active managed pointer context for the complete native access, or store the
pointer through a ctypesx record descriptor that establishes the managed pin.

## Buffer and memory utilities

These standard ctypes operations remain useful:

- `ctypes.sizeof` and `ctypes.alignment` for layout inspection;
- `ctypes.string_at` and `wstring_at` when the native contract establishes a
  valid NUL-terminated address;
- `ctypes.CDLL` and `PyDLL` for loading libraries; and
- `ctypes.cast`, `addressof`, `byref`, `memmove`, and `memset` for deliberately
  low-level code.

The last group bypasses some ctypesx checking or lifetime tracking. In
particular:

- `addressof`, `byref`, and an integer `.address` do not pin a dynamic record;
- `cast` can remove Python-level constness and semantic pointee conversion;
- `memmove`/`memset` can overwrite pointer fields without owner sidecars; and
- direct `ctypes.resize` must not be used on a ctypesx record.

Prefer checked record descriptors, managed pointers, memoryviews, and pointer
contexts wherever the native contract permits.

## Representation metadata

ctypesx semantic types carry immutable storage metadata used internally by the
record, pointer, and callback compilers. The current classes expose it as
`Type.__ctypesx_ctype__`, and enum classes additionally expose
`__ctypesx_underlying__`.

For public foreign-function prototypes, prefer the corresponding standard
ctypes scalar spelling (`ctypes.c_uint32`, for example) rather than making an
application depend on metadata names. Records and generated pointer/callback
types can be used directly.

## What ctypesx deliberately does not wrap

- library loading and symbol resolution;
- `errno` and Windows last-error management;
- variadic calls;
- arbitrary memory allocation/free APIs;
- `memmove`, `memset`, `string_at`, or general casts;
- platform-specific loader and callback conventions; and
- C header parsing or automatic declaration generation.

This boundary keeps ctypesx focused on typed C data and lets existing ctypes
knowledge and ecosystem tools remain useful.
