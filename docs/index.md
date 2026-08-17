# ctypesx documentation

`ctypesx` extends the standard-library `ctypes` data model with checked Python
values, declarative records, typed pointers, flexible array members, bounded
views, and strict static typing. It deliberately leaves dynamic-library loading
and general FFI operations to `ctypes`.

## Start here

1. Follow [Getting started](getting-started.md) to define and use a record.
2. Read [ctypes interoperability](ctypes-interop.md) before configuring a
   `CDLL` function prototype.
3. If an existing binding uses ctypes, use
   [Migrating from ctypes](migration-from-ctypes.md).
4. Read [Ownership and safety](ownership-and-safety.md) before passing pointers
   or resizable records to native code.

## Concepts and guides

| Topic | Document |
|---|---|
| Checked C values and exact Python types | [Scalars](scalars.md) |
| C enums and bit masks | [Enums and flags](enums-and-flags.md) |
| Declarative layout and buffers | [Structures and unions](records.md) |
| Fixed arrays, bit-fields, and dynamic tails | [Arrays and FAMs](arrays-and-fam.md) |
| Typed addresses, strings, and ownership | [Pointers and strings](pointers-and-strings.md) |
| Native callable signatures | [Callbacks](callbacks.md) |
| Bounded pointer views | [Span and ConstSpan](spans.md) |
| CDLL and raw ctypes integration | [ctypes interoperability](ctypes-interop.md) |
| Lifetime, relocation, and unsafe escape hatches | [Ownership and safety](ownership-and-safety.md) |
| Pyright guarantees and limits | [Static typing](typing.md) |
| Native ABI assumptions | [Layout and portability](layout-and-portability.md) |
| Copies, FAM complexity, and hot paths | [Performance and copy model](performance.md) |

## Reference and project information

- [Public API index](api-reference.md)
- [Current limitations](limitations.md)
- [Development guide](development.md)
- [Contributing](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)
- [Changelog](../CHANGELOG.md)

## The central model

ctypesx separates two roles that raw ctypes often represents with one class:

1. A **Python semantic type** controls the value a user reads and the Python
   inputs accepted during assignment. `U8`, for example, is a checked subclass
   of `int`.
2. A **C storage type** controls size, alignment, byte order, and ABI exchange.
   `U8` uses the host `ctypes.c_uint8` representation.

`CStruct` combines those roles. The annotation remains visible to Pyright, and
the metaclass compiles it into a real `ctypes.Structure` layout. Field
descriptors convert between semantic values and storage.

This means a record, generated pointer, or generated callback is directly
usable where ctypes expects that ABI category, while a scalar such as `U8` is
not itself a ctypes `_SimpleCData` class. See
[ctypes interoperability](ctypes-interop.md) for examples.

## Support policy

The current source version is the unreleased `0.1.0`, project maturity is
experimental, and CPython 3.14 or newer is required. Layout is always
host-native. Documented package-root re-exports are the canonical convenience
API. The documented category modules (`scalar`, `enums`, `field`, `records`,
`array`, and `pointer`) are also supported import paths; incidental names and
private helpers reachable from those modules are implementation details.

The project currently tests strict typing with Pyright. Other type checkers may
work, but are not part of the compatibility promise yet.
