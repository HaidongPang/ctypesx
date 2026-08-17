# Contributing to ctypesx

Thank you for helping improve ctypesx. The project is an experimental native
ABI library, so changes must preserve both Python semantics and real C layout.

## Development setup

Requirements:

- CPython 3.14 or newer;
- [uv](https://docs.astral.sh/uv/); and
- Git.

```console
git clone https://github.com/HaidongPang/ctypesx.git
cd ctypesx
uv sync
```

## Before opening a change

Run:

```console
uv run pytest
uv run pyright
uv lock --check
uv build
git diff --check
```

Changes to ABI declarations or layout code should also be validated against a
small C probe compiled from the authoritative header on every affected target.
Matching an existing ctypes declaration alone is not sufficient proof.

## Change requirements

- Add runtime tests for conversion, layout, failure cases, and ownership.
- Add strict Pyright assertions for public constructor, field, pointer, or
  callback behavior.
- Keep multi-element writes atomic with respect to conversion failure.
- Never silently approximate an unsupported C layout.
- Document every new public root import in
  [the API index](docs/api-reference.md).
- Update [the migration guide](docs/migration-from-ctypes.md) when behavior
  differs from raw ctypes.
- Add a user-visible entry under `Unreleased` in
  [CHANGELOG.md](CHANGELOG.md).

For dynamic records and pointers, test held views, reallocation, pins, owner
release, raw external overwrite, borrowed buffers, and callback lifetime as
applicable.

## Scope

ctypesx is focused on typed enhancements for native C values built on ctypes.
It is not intended to become a C parser, code generator, dynamic adapter
registry, general native allocator, or cross-target serialization engine.

Discuss a large API or architectural addition in an issue before implementing
it. Small fixes, tests, and documentation improvements can be proposed directly.

## Documentation style

- README should remain a concise project entry point.
- Detailed rules belong in `docs/` and should link to related safety material.
- Happy-path snippets should be executable where practical.
- Unsafe raw-address examples must say what cannot be validated.
- Use `ctypes` for the module and `ctypesx` for this package consistently.

See [the full development guide](docs/development.md) for repository structure,
typing strategy, and the release checklist.

## Security reports

Do not publish a memory-safety or vulnerability report in a public issue before
reading [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
