"""Owner-mode hybrid retrieval must use the on-disk Tantivy index, not the local catalog."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import retrieval_index
from app.services.tantivy_index import TextUnitIndex


@pytest.mark.asyncio
async def test_require_lexical_index_for_hybrid_skips_local_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "tantivy"
    monkeypatch.setattr(retrieval_index, "index_directory", lambda: index_dir)
    stub_index = MagicMock(spec=TextUnitIndex)
    retrieval_index.set_index(stub_index, index_dir)

    owner_runtime = MagicMock()
    owner_runtime.client = object()
    monkeypatch.setattr(retrieval_index, "get_owner_runtime", lambda: owner_runtime)

    ensure_current = AsyncMock(return_value=0)
    with patch(
        "app.services.tantivy_generation.SearchIndexer.ensure_current", ensure_current,
    ), patch(
        "app.services.retrieval_index.require_current_index",
        side_effect=AssertionError("must not open the local knowledge catalog"),
    ):
        index = await retrieval_index.require_lexical_index_for_hybrid()

    assert index is stub_index
    ensure_current.assert_awaited_once()
    retrieval_index.set_index(None)