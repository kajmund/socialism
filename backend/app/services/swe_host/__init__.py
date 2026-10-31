"""Socialism's host context for SWE: tenant, feature and OverGraph catalog path.

This module belongs to the application, not to the engine. The engine never
validates a feature vocabulary or knows a catalog layout; it only receives the
resources and the store it is given. See ``docs/swe-standalone/10-pr1-b1-python-boundary.md``.
"""

from app.services.swe_host.context import (
    WorkflowHostContext,
    workflow_catalog_dir,
)

__all__ = [
    "WorkflowHostContext",
    "workflow_catalog_dir",
]
