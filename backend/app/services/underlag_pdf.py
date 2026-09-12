"""Convert Word (.docx) underlag to PDF via LibreOffice (soffice)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class UnderlagPdfConversionError(Exception):
    """LibreOffice could not convert the document to PDF."""


def _resolve_soffice() -> str:
    configured = settings.libreoffice_bin.strip()
    if configured:
        path = Path(configured)
        if path.is_file() or shutil.which(configured):
            return configured
        raise UnderlagPdfConversionError(
            f"LIBREOFFICE_BIN={configured!r} not found — install LibreOffice or set the path"
        )
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if not found:
        raise UnderlagPdfConversionError(
            "LibreOffice (soffice) is required to convert Word documents to PDF"
        )
    return found


def convert_docx_to_pdf(data: bytes, *, filename: str = "document.docx") -> bytes:
    """Run LibreOffice headless conversion. Fail loud on any error."""
    soffice = _resolve_soffice()
    stem = Path(filename).stem or "document"
    with tempfile.TemporaryDirectory(prefix="underlag-docx-") as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / f"{stem}.docx"
        src.write_bytes(data)
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_dir),
                str(src),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")[:500]
            raise UnderlagPdfConversionError(
                f"LibreOffice conversion failed (exit {result.returncode}): {stderr}"
            )
        pdf_path = tmp_dir / f"{stem}.pdf"
        if not pdf_path.is_file():
            raise UnderlagPdfConversionError("LibreOffice did not produce a PDF")
        pdf_bytes = pdf_path.read_bytes()
        if not pdf_bytes.startswith(b"%PDF"):
            raise UnderlagPdfConversionError("LibreOffice output is not a valid PDF")
        return pdf_bytes


async def convert_docx_to_pdf_async(data: bytes, *, filename: str = "document.docx") -> bytes:
    return await asyncio.to_thread(convert_docx_to_pdf, data, filename=filename)
