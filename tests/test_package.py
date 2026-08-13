from __future__ import annotations

import ctypesx


def test_package_is_importable() -> None:
    assert ctypesx.__doc__ is not None
