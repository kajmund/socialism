from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sfs_atom() -> str:
    return (FIXTURES / "sfs_feed.atom").read_text(encoding="utf-8")


@pytest.fixture
def sfs_html() -> str:
    return (FIXTURES / "sfs_2017_193.html").read_text(encoding="utf-8")
