# Current limitations

This page lists deliberate boundaries of the unreleased, experimental ctypesx
`0.1.0` source. Unsupported declarations fail explicitly where possible rather
than producing an approximate ABI.

## Platform and layout

- CPython 3.14 or newer is required.
- Only the running process's host-native ABI is modeled.
- Cross-target layout is unsupported.
- Packed/custom `_pack_`, `_align_`, and `_layout_` policies are unsupported.
- Non-native endian record classes are unsupported.
- Free-threaded CPython is not supported; internal layout/type registries and
  dynamic-record bookkeeping are not synchronized.
- No platform support matrix is claimed until those targets are exercised in
  project CI and with native layout probes.

## Record declarations

- No forward or incomplete record declarations.
- No self-referential `Pointer[Node]` declaration during `Node` class creation.
- No concrete-record inheritance; use composition.
- No ordinary ctypes scalar or ordinary ctypes record fields inside a
  `CStruct`/`CUnion` declaration.
- No anonymous-union field flattening.
- No unnamed or zero-width bit-fields.
- `CChar` is not a supported bit-field storage type; use a signed/unsigned char
  integer scalar when the C declaration permits it.
- No custom annotation metadata beyond `Bits` and `Length`.
- A C field may shadow inherited class APIs such as `from_buffer`; there is no
  field-alias mechanism.

## Arrays and flexible tails

- `Array` is a field view and cannot be constructed directly by applications.
- A dynamic-tail record cannot be an `Array` or `FamArray` element.
- A fixed `Array` cannot currently be the element of a `FamArray`; nested FAM
  element dimensions have no declaration syntax yet.
- A direct FAM must be final, unique, and follow at least one named field.
- The dynamic tail offset must equal the static record `sizeof`; layouts with
  ambiguous trailing padding are rejected.
- A separate count/capacity/byte-length field is never synchronized
  automatically.
- `from_address` is unavailable for dynamic records because an address carries
  no tail extent.
- Borrowed `from_buffer` records cannot change extent.
- Dynamic nested records and alternative union FAM interpretations are ctypesx
  extensions for modeling existing ABIs, not literal ISO C multiple-FAM
  declarations.

## Pointers and safety

- Bare `Pointer`, `ConstPointer`, and `FunctionPointer` are type factories, not
  supported ABI instances; always parameterize them before construction.
- Raw addresses are validated only as native-width unsigned integers.
- `Pointer.known_length` does not bounds-check pointer indexing.
- `ConstPointer` and `ConstSpan` enforce constness only through checked Python
  methods.
- A Python sequence or string creates an owned snapshot, not a borrowed view.
- Owner sidecars do not survive `bytes`, `memmove`, external writes, or buffer
  copies.
- ctypes raw operations can bypass conversion, ownership, fingerprint, and pin
  tracking.
- ctypesx cannot infer how long foreign code retains a pointer or callback.
- Direct `ctypes.resize` of a ctypesx record is unsupported and unsafe.

## Span

- `Span` and `ConstSpan` are Python views, not C ABI records or ctypes argument
  types.
- They do not implement the Python buffer protocol.
- Direct sequence construction cannot express every descriptor input constraint
  to Pyright, although runtime conversion remains strict.
- Generic pointer/span sequence annotations can admit byte containers that
  runtime generic conversion deliberately excludes.
- Mutable `Span.pointer` currently has the broader static return type
  `Pointer[T] | ConstPointer[T]`, although runtime construction guarantees the
  mutable branch.

## Callbacks

- Fixed-arity `ctypes.CFUNCTYPE` only.
- No variadic callbacks.
- No `WINFUNCTYPE` model.
- No `use_errno` or `use_last_error` signature variants.
- Python exceptions must be caught inside callbacks.
- Every pointer-result invocation retains a token until callback destruction;
  repeated new owned buffers additionally retain their full backing memory.
- Structures and unions are not supported as by-value callback result types;
  use a pointer or out-parameter.
- Raw ctypes scalar types are accepted in `FunctionPointer` signatures, but
  runtime callbacks receive/return ctypes' Python primitives while the generic
  annotation names the ctypes class; this surface is not precisely typed.

## ctypes coverage

ctypesx does not wrap or replace:

- `CDLL`, `PyDLL`, or platform-specific loaders;
- general `argtypes`/`restype` scalar prototypes;
- allocation/free APIs;
- `memmove`, `memset`, `string_at`, or arbitrary casts;
- header parsing or binding generation; or
- portable serialization.

Semantic scalar and enum classes are not ctypes `_SimpleCData` types, so they
cannot be placed directly in a normal `CDLL.argtypes` or `restype` list. Use the
matching standard ctypes storage class and wrap results explicitly.

## Static analysis

- Pyright strict mode is the only checker currently verified by the project.
- Value-dependent conditions such as numeric range and ASCII content are
  runtime checks.
- Some dynamically generated pointer/function constructor surfaces expose
  `Any` to a checker.
- More dynamic raw-ctypes and pointer-to-pointer combinations may require an
  explicit cast.

See [Static typing](typing.md) for the exact supported surface.
