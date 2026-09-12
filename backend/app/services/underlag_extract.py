"""Extract text from personal underlag uploads (txt/md/pdf/docx).

Extraction is deferred until experts need the text (panel run / suggest).
Upload only stores the original file (Word is converted to PDF first).
"""

from __future__ import annotations

from io import BytesIO
from typing import Literal

import mammoth
import pdfplumber
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import StoredObject
from app.services.object_storage import UNDERLAG_DOCX_TYPE

ExtractionStatus = Literal["pending", "ok", "failed", "empty", "unsupported"]


def extract_underlag_text(content_type: str, data: bytes) -> tuple[str | None, ExtractionStatus]:
    if content_type in {"text/plain", "text/markdown"}:
        return _finish(_extract_plaintext(data))
    if content_type == "application/pdf":
        return _finish(_extract_pdf(data))
    if content_type == UNDERLAG_DOCX_TYPE:
        return _finish(_extract_docx(data))
    return None, "unsupported"


async def ensure_underlag_extracted(
    session: AsyncSession,
    row: StoredObject,
    *,
    read_bytes,
) -> str:
    """Extract and persist text if needed. Returns non-empty extracted text or raises."""
    if row.extraction_status == "ok" and (row.extracted_text or "").strip():
        return (row.extracted_text or "").strip()

    data, content_type = await read_bytes(row)
    extracted, status = extract_underlag_text(content_type, data)
    if status != "ok":
        extracted = None
    row.extracted_text = extracted
    row.extraction_status = status
    await session.flush()
    text = (extracted or "").strip()
    if status != "ok" or not text:
        raise ValueError(f"Underlag extraction status is {status!r}")
    return text


def _finish(text: str | None) -> tuple[str | None, ExtractionStatus]:
    if text is None:
        return None, "failed"
    stripped = text.strip()
    if not stripped:
        return None, "empty"
    return stripped, "ok"


def _extract_plaintext(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _extract_pdf(data: bytes) -> str | None:
    try:
        pages: list[str] = []
        with pdfplumber.open(BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    except Exception:
        return None


def _extract_docx(data: bytes) -> str | None:
    try:
        result = mammoth.convert_to_markdown(BytesIO(data))
        return str(result.value or "")
    except Exception:
        return None
