# ctypesx

`ctypesx` is a typed, checked, and declarative extension layer for Python's
standard [`ctypes`](https://docs.python.org/3/library/ctypes.html) module.

The project is intended to provide:

- runtime-checked fixed-width C integer values;
- precisely typed enums and flags;
- annotation-defined C structures and unions;
- typed fixed arrays, bit fields, and flexible array members;
- zero-copy buffer-backed records with explicit ownership semantics; and
- generated typing information for record fields and constructors.

`ctypesx` builds on the host-native layouts provided by `ctypes`. It is not a C
header parser, binding generator, cross-target layout engine, or replacement
for the complete `ctypes` FFI.

## Status

The repository currently contains the initial package scaffold. The runtime
will be extracted and generalized from the infrastructure developed for
[`kvm-abi`](https://github.com/HaidongPang/kvm-abi).

## Development

The project uses [uv](https://docs.astral.sh/uv/):

```console
uv sync
uv run pytest
uv run pyright
uv build
```

## License

`ctypesx` is licensed under the [MIT License](LICENSE).
