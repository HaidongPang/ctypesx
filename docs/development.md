# Development guide

ctypesx is a pure-Python project managed with [uv](https://docs.astral.sh/uv/).
It requires CPython 3.14 because the implementation relies on the current
annotation and buffer protocols.

## Set up the checkout

```console
git clone https://github.com/HaidongPang/ctypesx.git
cd ctypesx
uv sync
```

The locked development environment contains pytest and Pyright. There are no
runtime dependencies.

## Repository layout

```text
ctypesx/
├── src/ctypesx/
│   ├── scalar.py       # checked scalar values and aliases
│   ├── enums.py        # fixed-storage enum and flag bases
│   ├── field.py        # Field, Bits, and Length declarations
│   ├── records.py      # annotation compiler, records, buffers, FAM state
│   ├── array.py        # fixed and flexible zero-copy views
│   ├── pointer.py      # pointers, strings, callbacks, spans, pointer_to
│   └── py.typed        # PEP 561 marker
├── tests/              # runtime and documentation tests
├── typing_tests/       # strict positive/negative Pyright assertions
├── examples/           # runnable documentation examples
├── docs/               # Markdown documentation
└── pyproject.toml
```

## Required verification

Run all checks before submitting a change:

```console
uv run pytest
uv run pyright
uv lock --check
uv build
```

Also run:

```console
git diff --check
```

The test suite covers runtime conversion/layout/ownership behavior. The
`typing_tests/` directory contains code that should be accepted as well as
intentional errors annotated with precise Pyright suppressions; an unnecessary
suppressions policy catches regressions that accidentally weaken or strengthen
the type surface.

## Adding a C value category

ctypesx intentionally supports C's native value categories rather than a public
adapter/plugin registry. A new built-in category should define all of:

1. the native ctypes storage class;
2. the Python semantic read type;
3. accepted Python assignment inputs;
4. exact runtime conversion and overflow behavior;
5. field, array, pointer, callback, and nested-owner behavior where applicable;
6. strict static typing coverage; and
7. documentation and portability constraints.

Do not accept a value by silently delegating to a ctypes conversion that can
truncate or lose ownership unless that behavior is the explicit documented
contract.

## Record changes

Record code must preserve these invariants:

- annotation order equals native field order;
- unsupported layout never degrades silently;
- conversion is staged before multi-element commit;
- nested views follow owned FAM relocation;
- borrowed extents never resize;
- every exported tracked address prevents relocation;
- owner sidecars recursively follow record/array assignment; and
- raw external overwrites invalidate sidecars safely on checked reads.

Any change to FAM extent, nested unions, pointer fields, buffers, or pinning
needs focused tests for owner lifetime and held-view relocation in addition to
the ordinary happy path.

## Typing changes

The annotation used by the record compiler is also user-facing typing API. A
runtime-only improvement that weakens constructor/field inference is a
regression.

Add `typing.assert_type` checks for new reads and valid operations. Add an
intentional invalid call with a narrow Pyright ignore for every input category
that should be rejected. Keep `reportUnnecessaryTypeIgnoreComment = "error"`
enabled.

Only Pyright strict mode is currently promised. Supporting another checker
requires adding it to automated verification and documenting checker-specific
limits.

## Documentation changes

- Keep README as a concise entry point; put detailed behavior in `docs/`.
- Every public root import belongs in [the API index](api-reference.md).
- Put executable happy-path examples in `examples/` or documentation tests.
- Mark intentionally invalid code as such and avoid placing uncaught failures
  in the README quick start.
- Update the migration guide whenever behavior differs from raw ctypes.
- Update `CHANGELOG.md` for user-visible behavior.

Documentation uses relative Markdown links so it renders without a site
generator. The test suite checks local links, compiles Python fences, and
executes files under `examples/`.

## Release checklist

1. Update version and changelog.
2. Run the complete test/type/link suite on each claimed platform.
3. Validate record layouts against native C probes for supported ABI targets.
4. Run `uv lock --check` and `uv build`.
5. Install the wheel in a fresh Python 3.14 environment.
6. Confirm the wheel contains `LICENSE`, README metadata, and `py.typed`.
7. Publish only after the README installation/status text matches reality.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the contributor-facing summary.
