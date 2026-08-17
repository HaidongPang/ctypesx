# Changelog

All notable user-visible changes to ctypesx are documented in this file.

The project follows [Semantic Versioning](https://semver.org/) once a stable
public API is established. The current `0.1` development series is experimental
and may contain breaking changes between releases.

## 0.1.0 - Unreleased

### Added

- Checked host-native and fixed-width C scalar values.
- Fixed-storage closed enums and bounded flags.
- Annotation-defined structures and unions.
- Typed fixed arrays, bit-fields, and list-like flexible array members.
- Typed mutable/const/string/void pointers and managed `pointer_to()`.
- Fixed-arity typed function pointers and callbacks.
- Bounded mutable `Span` and read-only `ConstSpan` views.
- Exact buffer-backed records, owner sidecars, relocation tracking, and pins.
- Inline strict typing with a `py.typed` marker and no code generation.

### Documentation

- Reorganized the README as a concise project entry point.
- Added complete guides for scalars, records, arrays/FAMs, pointers, callbacks,
  spans, ownership, typing, layout, performance, ctypes interoperability, and
  limitations.
- Added a detailed migration guide from raw ctypes.
- Added contributor, security, and development documentation.
