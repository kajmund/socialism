"""Stable identity of an organisation's required company workspace."""

from uuid import NAMESPACE_URL, uuid5


def company_workspace_id(customer_id: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"socialism:company-workspace:{customer_id}"))
