# Scalars

ctypesx scalar classes are immutable Python values with a fixed native C
representation. They preserve useful semantic types on field reads while
validating every conversion before bytes enter a record, array, pointer, or
callback.

They are not subclasses of ctypes `_SimpleCData`. Use ctypes scalar classes in
ordinary `CDLL.argtypes` and `restype`; see
[ctypes interoperability](ctypes-interop.md).

## Integer types

| C spelling | Canonical ctypesx type | Python value | Width |
|---|---|---|---|
| `signed char` | `CSChar` | `int` subclass | host-native |
| `unsigned char` | `CUChar` | `int` subclass | host-native |
| `short` | `CShort` | `int` subclass | host-native |
| `unsigned short` | `CUShort` | `int` subclass | host-native |
| `int` | `CInt` | `int` subclass | host-native |
| `unsigned int` | `CUInt` | `int` subclass | host-native |
| `long` | `CLong` | `int` subclass | host-native |
| `unsigned long` | `CULong` | `int` subclass | host-native |
| `long long` | `CLongLong` | `int` subclass | host-native |
| `unsigned long long` | `CULongLong` | `int` subclass | host-native |
| `int8_t` / `uint8_t` | `S8` / `U8` | `int` subclass | exactly 8 bits |
| `int16_t` / `uint16_t` | `S16` / `U16` | `int` subclass | exactly 16 bits |
| `int32_t` / `uint32_t` | `S32` / `U32` | `int` subclass | exactly 32 bits |
| `int64_t` / `uint64_t` | `S64` / `U64` | `int` subclass | exactly 64 bits |
| `size_t` / `ssize_t` | `CSize` / `CSSize` | `int` subclass | host-native |
| `intptr_t` / `uintptr_t` | `CIntPtr` / `CUIntPtr` | `int` subclass | host pointer width |

All integer types accept `typing.SupportsIndex`, except that `bool` is rejected
for ordinary integer types. Normal construction never truncates:

```python
from ctypesx import S8, U8


assert U8(255) == 255
U8(256)  # OverflowError
U8(-1)   # OverflowError
U8(True) # TypeError
```

Every `CInteger` subclass exposes:

- `BITS`: storage width in bits;
- `SIGNED`: whether its storage is signed;
- `bounds()`: inclusive numeric minimum and maximum;
- `wrap(value)`: explicit modulo-`2**BITS` truncation; and
- `from_bits(value)`: interpret an in-range unsigned bit pattern as the type.

```python
assert U8.wrap(-1) == U8(255)
assert S8.from_bits(0xFF) == S8(-1)
```

Use `wrap()` only where the C API explicitly specifies wraparound. It makes a
potentially lossy operation visible during review.

## `_Bool`, `char`, and `wchar_t`

| C type | ctypesx type | Accepted input | Read value |
|---|---|---|---|
| `_Bool` | `CBool` | `bool` or integer-compatible 0/1 | `CBool`, an `int` subclass equal to 0 or 1 |
| `char` | `CChar` | one ASCII `str`, one `bytes`, or integer-compatible 0..255 | `CChar`, an unsigned raw-byte `int` value |
| `wchar_t` | `CWChar` | exactly one host-representable `str` character | `CWChar`, a `str` subclass |

`CChar` intentionally differs from `ctypes.c_char`: reading it produces a
numeric value from 0 through 255 rather than a one-byte `bytes` object. This
keeps raw byte arithmetic and exact typing predictable regardless of whether
plain C `char` is signed on the host.

```python
from ctypesx import CBool, CChar, CWChar


assert CBool(True) == 1
assert CBool(0) == 0
assert CChar("A") == 0x41
assert CChar(b"\xff") == 0xFF
assert CWChar("λ") == "λ"
```

`CChar("é")` is rejected because string conversion is ASCII-only. A raw byte
such as `b"\xff"` remains valid. `CWChar` follows the host `wchar_t` size and
representation.

## Floating-point types

| C type | ctypesx type | Python value |
|---|---|---|
| `float` | `CFloat` | `float` subclass quantized to host C `float` |
| `double` | `CDouble` | `float` subclass quantized to host C `double` |
| `long double` | `CLongDouble` | `float` subclass using native layout |

Floating types accept `SupportsFloat` or `SupportsIndex`. Strings, bytes, and
`bool` are rejected. A finite Python input that would silently become infinity
at the target precision raises `OverflowError`; explicitly supplied infinities
remain valid.

Python exposes `long double` through Python `float`, so ctypesx preserves the
native size and layout but cannot preserve precision beyond the Python float
value returned by ctypes.

## Complex types

Python 3.14 may expose `ctypes.c_float_complex`, `c_double_complex`, and
`c_longdouble_complex` depending on the Python/libffi build. ctypesx maps them
to `CFloatComplex`, `CDoubleComplex`, and `CLongDoubleComplex`.

The classes are always importable so applications can perform feature
detection. Constructing one on a build without its matching ctypes
representation raises `NotImplementedError`; declaring it as a `CStruct` field
fails at class creation with `TypeError` because no C storage layout exists.
Feature-gate both construction and record declarations by inspecting the
standard ctypes module:

```python
import ctypes


if hasattr(ctypes, "c_float_complex"):
    from ctypesx import CFloatComplex

    value = CFloatComplex(1 + 2j)
```

## Aliases

Aliases describe exactly the same Python class and C representation; they do
not create nominally distinct types.

| Canonical name | Aliases |
|---|---|
| `CSChar` | `CSignedChar` |
| `CUChar` | `CUnsignedChar` |
| `CUShort` | `CUnsignedShort` |
| `CUInt` | `CUnsignedInt` |
| `CULong` | `CUnsignedLong` |
| `CULongLong` | `CUnsignedLongLong` |
| `S8`, `S16`, `S32`, `S64` | `CInt8`, `CInt16`, `CInt32`, `CInt64` |
| `U8`, `U16`, `U32`, `U64` | `CUInt8`, `CUInt16`, `CUInt32`, `CUInt64` |
| `CSize`, `CSSize` | `CSizeT`, `CSSizeT` |
| `CIntPtr`, `CUIntPtr` | `CIntPtrT`, `CUIntPtrT` |

## Arithmetic and immutability

Scalar values are Python numeric subclasses, so normal arithmetic follows
Python rules and generally returns a plain Python number:

```python
from ctypesx import U8


result = U8(250) + U8(10)
assert type(result) is int
assert result == 260
```

The next explicit construction or checked field assignment validates the
result. ctypesx does not overload every Python operator with C overflow rules.

`CInteger` representation metadata is immutable after class creation. A
semantic integer subclass may inherit an existing representation, but cannot
change its width, signedness, or storage class. Custom subclasses of the other
scalar families are not a documented extension mechanism.

A semantic integer subclass is useful for nominal domain distinctions while
retaining the same C representation:

```python
from ctypesx import CInt


class FileDescriptor(CInt):
    pass
```

A field declared as `FileDescriptor` reads back that exact type and still uses
the host C `int` layout.

## Error categories

- `TypeError`: the Python input category is unsupported, such as `U8(True)`.
- `ValueError`: the category is valid but the semantic value is invalid, such
  as `CBool(2)` or `CChar("AB")`.
- `OverflowError`: the numeric value does not fit the C representation.

These distinctions are consistent across scalar fields, array elements,
pointer buffers, and callback conversion.
