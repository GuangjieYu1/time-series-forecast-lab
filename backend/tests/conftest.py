from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.generate_fixtures import ensure_fixtures


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session", autouse=True)
def generated_fixtures() -> Path:
    ensure_fixtures()
    return Path(__file__).resolve().parent / "fixtures"
