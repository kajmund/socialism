from __future__ import annotations

import pytest

from app.services.rattsunderlag.lagen_nu import LagenNuNotFoundError
from app.services.rattsunderlag.lagen_nu_mock import MockLagenNuClient


@pytest.mark.asyncio
async def test_mock_search_law_and_get_sfs():
    client = MockLagenNuClient()
    hits = await client.search_law("offentlig upphandling LOU")
    assert [row.sfs_id for row in hits] == ["2016:1145"]
    sfs = await client.get_sfs("2016:1145")
    assert sfs.rubrik == "Lag om offentlig upphandling"
    assert sfs.forarbete_referens == "prop. 2015/16:195"


@pytest.mark.asyncio
async def test_mock_search_case_law():
    client = MockLagenNuClient()
    hits = await client.search_case_law("upphandling anbud")
    assert [row.referens for row in hits] == ["HFD 2019 ref. 65"]


@pytest.mark.asyncio
async def test_mock_get_forarbete():
    client = MockLagenNuClient()
    prop = await client.get_forarbete("prop. 2015/16:195")
    assert "likabehandling" in prop.utdrag.lower()


@pytest.mark.asyncio
async def test_mock_empty_search_and_unknown_ids():
    client = MockLagenNuClient()
    assert await client.search_law("xyzzy-no-hit") == []
    assert await client.search_case_law("xyzzy-no-hit") == []
    with pytest.raises(LagenNuNotFoundError, match="SFS"):
        await client.get_sfs("9999:0")
    with pytest.raises(LagenNuNotFoundError, match="förarbete"):
        await client.get_forarbete("prop. 1900:1")
