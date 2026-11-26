"""Shared pytest fixtures.

`test_parsers.py` was written as a script with a `main(root)` runner, so its test
functions take a `root: Path` argument that pytest tries to resolve as a fixture. This
provides it, which lets the same file run under both runners.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def root() -> Path:
    """Repository root, the same value the script runner passes in."""
    return Path(__file__).resolve().parent.parent