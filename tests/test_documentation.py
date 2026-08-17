from __future__ import annotations

import ast
import re
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    *sorted((ROOT / "docs").glob("*.md")),
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
PYTHON_FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)


@pytest.mark.parametrize(
    "document",
    MARKDOWN_FILES,
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_local_documentation_links_resolve(document: Path) -> None:
    contents = document.read_text(encoding="utf-8")
    prose = re.sub(r"```.*?```", "", contents, flags=re.DOTALL)
    prose = re.sub(r"`[^`\n]*`", "", prose)
    for match in MARKDOWN_LINK.finditer(prose):
        destination = match.group(1).strip()
        if destination.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_text = destination.split("#", 1)[0]
        if not path_text:
            continue
        target = (document.parent / path_text).resolve()
        assert target.exists(), (
            f"{document.relative_to(ROOT)} links to missing {destination!r}"
        )


@pytest.mark.parametrize(
    "example",
    sorted((ROOT / "examples").glob("*.py")),
    ids=lambda path: path.name,
)
def test_documented_examples_run(example: Path) -> None:
    runpy.run_path(str(example))


@pytest.mark.parametrize(
    "document",
    MARKDOWN_FILES,
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_python_documentation_blocks_compile(document: Path) -> None:
    contents = document.read_text(encoding="utf-8")
    for index, match in enumerate(PYTHON_FENCE.finditer(contents), start=1):
        compile(
            match.group(1),
            f"{document.relative_to(ROOT)}:python-block-{index}",
            "exec",
        )


def test_api_index_mentions_every_explicit_root_reexport() -> None:
    package = ast.parse(
        (ROOT / "src" / "ctypesx" / "__init__.py").read_text(
            encoding="utf-8"
        )
    )
    exported = {
        alias.asname or alias.name
        for node in package.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    api_index = (ROOT / "docs" / "api-reference.md").read_text(
        encoding="utf-8"
    )
    documented = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)", api_index))

    assert exported <= documented
