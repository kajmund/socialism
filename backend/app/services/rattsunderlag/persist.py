"""Save a rättsutredning as personal underlag (StoredObject)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import StoredObject
from app.services.rattsunderlag import MODULE_ID
from app.services.report.rattsutredning import (
    RattsutredningPayload,
    render_rattsutredning_markdown,
)
from app.services.stored_objects import upload_underlag


async def save_rattsunderlag_underlag(
    session: AsyncSession,
    *,
    customer_id: int,
    owner_user_id: str,
    payload: RattsutredningPayload,
    locale: str,
    filename: str,
) -> StoredObject:
    markdown = render_rattsutredning_markdown(payload, locale=locale)
    return await upload_underlag(
        session,
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        module=MODULE_ID,
        filename=filename,
        content_type="text/markdown",
        data=markdown.encode("utf-8"),
    )
