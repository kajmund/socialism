"""Host-context isolation for workflow catalog directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.swe.errors import SwdValidationError
from app.services.swe_host import WorkflowHostContext, workflow_catalog_dir
from app.services.swe_host.context import FEATURE_IDS


def test_catalog_dir_is_per_customer_and_feature(tmp_path: Path) -> None:
    research = workflow_catalog_dir(
        tmp_path,
        WorkflowHostContext(customer_id="acme", feature_id="research"),
    )
    routing = workflow_catalog_dir(
        tmp_path,
        WorkflowHostContext(customer_id="acme", feature_id="model_routing"),
    )
    other = workflow_catalog_dir(
        tmp_path,
        WorkflowHostContext(customer_id="beta", feature_id="research"),
    )
    assert research == tmp_path / "workflows" / "customer_acme" / "research"
    assert routing == tmp_path / "workflows" / "customer_acme" / "model_routing"
    assert other == tmp_path / "workflows" / "customer_beta" / "research"
    assert research != other
    assert research != routing


def test_nested_model_routing_stays_in_research_catalog() -> None:
    context = WorkflowHostContext(customer_id="acme", feature_id="research")
    path = workflow_catalog_dir(Path("/var/swe"), context)
    assert path.parts[-1] == "research"
    assert "model_routing" not in path.parts


def test_path_traversal_customer_id_is_rejected() -> None:
    with pytest.raises(SwdValidationError, match="invalid customer_id"):
        WorkflowHostContext(customer_id="../etc", feature_id="research")


def test_unknown_feature_is_rejected() -> None:
    with pytest.raises(SwdValidationError, match="unknown feature_id"):
        WorkflowHostContext(customer_id="acme", feature_id="not_a_feature")


def test_feature_registry_matches_spec() -> None:
    assert FEATURE_IDS == {
        "research",
        "expert_routing",
        "model_routing",
        "group_chat",
        "webcrawler",
    }
