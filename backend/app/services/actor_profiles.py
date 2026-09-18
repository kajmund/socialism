"""On-demand context and proposed edits, scoped by the authenticated caller."""

import json
from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import assert_kund_access
from app.database.models import ActorContextProposal, Kund, UserAccount
from app.schemas.profiles import OrganizationFields, ProfileFields
from app.services.profiles import organization_values, profile_values

ActorToolHandler = Callable[[str, dict], Awaitable[str]]

ACTOR_TOOL_IDS = frozenset({"get_actor_context", "propose_actor_context_update"})


class ProposedEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["current_user", "customer"]
    changes: dict[str, str | None] = Field(min_length=1, max_length=8)


def actor_tool_specs() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_actor_context",
                "description": "Read the current user's profile and the customer for this conversation when needed.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_actor_context_update",
                "description": "Propose exact profile or organization changes for user approval. This does not save the changes.",
                "parameters": ProposedEdit.model_json_schema(),
            },
        },
    ]


def serialize_proposal(row: ActorContextProposal) -> dict:
    return {
        k: getattr(row, k)
        for k in ("id", "conversation", "target", "target_label", "changes", "previous", "status")
    }


class ActorProfileTools:
    def __init__(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        customer_id: int | None,
        conversation: str,
        requested_by_id: str | None = None,
    ):
        self.session = session
        self.user_id = user_id
        self.customer_id = customer_id
        self.conversation = conversation
        self.requested_by_id = requested_by_id

    async def __call__(self, name: str, arguments: dict) -> str:
        user = await self.session.get(UserAccount, self.user_id, populate_existing=True)
        if user is None:
            raise ValueError("actor_not_found")
        if self.customer_id is not None:
            assert_kund_access(user, self.customer_id)
        customer = (
            await self.session.get(Kund, self.customer_id, populate_existing=True)
            if self.customer_id is not None
            else None
        )
        if name == "get_actor_context":
            if arguments:
                raise ValueError("get_actor_context takes no arguments")
            requester = (
                await self.session.get(UserAccount, self.requested_by_id)
                if self.requested_by_id
                else None
            )
            # Never expose an unrelated account from a stale or incorrect job context.
            if requester and requester.role != "admin" and requester.kund_id != self.customer_id:
                requester = None
            result = {
                "current_user": {"id": user.id, **profile_values(user)},
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                    **organization_values(customer),
                }
                if customer
                else None,
                "requested_by": {"id": requester.id, **profile_values(requester)}
                if requester
                else None,
            }
            return json.dumps(result, ensure_ascii=False)
        if name != "propose_actor_context_update":
            raise ValueError("unknown_actor_tool")
        edit = ProposedEdit.model_validate(arguments)
        if edit.target == "customer":
            if user.role != "admin" or customer is None:
                return json.dumps({"error": "customer_edit_requires_admin"})
            row = customer
            body = OrganizationFields.model_validate(edit.changes)
            label = customer.name
        else:
            row = user
            body = ProfileFields.model_validate(edit.changes)
            label = " ".join(filter(None, (user.first_name, user.last_name))) or user.email
        changes = {k: v or None for k, v in body.model_dump(exclude_unset=True).items()}
        if changes.get("country_code"):
            code = changes["country_code"].upper()
            if len(code) != 2 or not code.isascii() or not code.isalpha():
                raise ValueError("invalid_country_code")
            changes["country_code"] = code
        previous = {k: getattr(row, k) for k in changes}
        if changes == previous:
            return json.dumps({"status": "unchanged"})
        # A repeated model call must not produce repeated approval cards.
        existing = (
            await self.session.scalars(
                select(ActorContextProposal).where(
                    ActorContextProposal.user_id == user.id,
                    ActorContextProposal.conversation == self.conversation,
                    ActorContextProposal.status == "pending",
                    ActorContextProposal.target == edit.target,
                    ActorContextProposal.customer_id == self.customer_id,
                )
            )
        ).all()
        for proposal in existing:
            if proposal.changes == changes and proposal.revision == row.profile_revision:
                return json.dumps(serialize_proposal(proposal), ensure_ascii=False)
        proposal = ActorContextProposal(
            id=uuid4().hex,
            user_id=user.id,
            customer_id=self.customer_id,
            conversation=self.conversation,
            target=edit.target,
            target_label=label,
            changes=changes,
            previous=previous,
            revision=row.profile_revision,
            status="pending",
        )
        self.session.add(proposal)
        await self.session.commit()
        return json.dumps(
            {**serialize_proposal(proposal), "approval_path": "/profil", "saved": False},
            ensure_ascii=False,
        )
