from pathlib import Path

import pytest

MOCK = Path(__file__).resolve().parents[1] / "mock"


@pytest.fixture
def mock_dir() -> Path:
    return MOCK
