# Enums and flags

ctypesx enums combine Python `IntEnum`/`IntFlag` behavior with an explicit C
integer storage type. No enum or flag silently assumes a 32-bit representation.

## Closed enums

Choose a fixed-underlying base that matches the C declaration:

```python
from ctypesx import CStruct, Field, U16Enum


class Mode(U16Enum):
    OFF = 0
    ON = 1


class Device(CStruct):
    mode: Mode = Field()


device = Device(mode=1)
assert device.mode is Mode.ON
```

`CEnum` is closed. A value inside the storage range but absent from the class
raises `ValueError`; a value outside the storage range raises `OverflowError`.
Enum members are validated when the class is created.

If an ABI must accept and round-trip future unknown numeric values, use the
underlying scalar type such as `U16` instead of an enum.

The same advice applies to native callbacks that may receive untrusted or newer
values. Callback argument conversion happens before the Python callable runs,
so use the open scalar in the signature and construct the closed enum inside the
callable where its `ValueError` can be handled.

## Flags and unknown bits

`CFlag` is intended for C bit masks:

```python
from ctypesx import U32Flag


class Feature(U32Flag):
    READ = 1 << 0
    WRITE = 1 << 1


features = Feature.READ | Feature.WRITE
future = Feature(1 << 31)
combined = features | future
```

Unknown bits are retained as long as the complete pattern fits the underlying
storage. This permits an older binding to round-trip flags introduced by a
newer producer. ctypesx fixes the enum boundary policy to `enum.KEEP`.

Bitwise inversion is bounded by the mask formed from declared flag members,
not by every bit in the storage width. It therefore follows named flag-domain
semantics rather than producing an arbitrary wide complement.

## Signed flag storage

C APIs occasionally store a bit mask in a signed integer. ctypesx keeps the
logical bit pattern and the signed storage value distinct:

```python
from ctypesx import S8Flag


class SignedFeature(S8Flag):
    LOW = 0x01
    HIGH = 0x80


assert int(SignedFeature.HIGH) == 0x80
assert SignedFeature.HIGH.value == -128
assert int(SignedFeature(-1)) == 0xFF
```

`int(flag)` is the complete non-negative bit pattern. `.value` is the exact
signed ctypesx scalar stored in C. Construction accepts either an in-range
logical pattern or the corresponding in-range signed storage value.

## Available bases

Every supported integer storage has matching `Enum` and `Flag` bases.

Fixed width:

- `S8Enum`, `U8Enum`, `S16Enum`, `U16Enum`, `S32Enum`, `U32Enum`,
  `S64Enum`, `U64Enum`;
- `S8Flag`, `U8Flag`, `S16Flag`, `U16Flag`, `S32Flag`, `U32Flag`,
  `S64Flag`, `U64Flag`.

Native C integer width:

- `CSCharEnum`, `CUCharEnum`, `CShortEnum`, `CUShortEnum`, `CIntEnum`,
  `CUIntEnum`, `CLongEnum`, `CULongEnum`, `CLongLongEnum`,
  `CULongLongEnum`, `CSizeEnum`, `CSSizeEnum`, `CIntPtrEnum`,
  `CUIntPtrEnum`;
- matching names ending in `Flag`.

These bases give `.value` its exact scalar type both at runtime and under
static analysis:

```python
from typing import assert_type

from ctypesx import U16


assert_type(Mode.ON.value, U16)
```

## General underlying-type form

The runtime also accepts an explicit class keyword:

```python
from ctypesx import CEnum, CFlag, U16


class Mode(CEnum, underlying=U16):
    OFF = 0
    ON = 1


class Feature(CFlag, underlying=U16):
    READ = 1
```

This form has the same exact runtime layout. Python's type system cannot derive
a dependent `.value` return type from a class keyword, so static analysis sees
`.value` as the broader `CInteger`. Prefer the fixed-underlying convenience
bases in public typed APIs.

Defining a concrete `CEnum` or `CFlag` without `underlying=` is an error. The
functional `Enum` construction API is not part of the supported surface.

## Choosing enum, flag, or scalar

| C contract | Recommended type |
|---|---|
| finite set; unknown values are invalid | `U*Enum` or native-width enum base |
| bit mask; unknown future bits must round-trip | `U*Flag` or native-width flag base |
| open numeric namespace or versioned numeric values | underlying scalar such as `U32` |

This choice expresses ABI semantics. Storage width alone is not enough to
decide whether an unknown value should be rejected.
