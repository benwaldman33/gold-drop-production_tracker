"""Pytest startup stabilization helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _app_context():
    """Provide a process-wide app context for utility tests that touch settings."""
    import app as app_module

    with app_module.app.app_context():
        yield
