from overgraph_ingest.extraction.cache import load_extracted, store_extracted
from overgraph_ingest.extraction.docx import extract_docx
from overgraph_ingest.extraction.model import ExtractedDocument, failed_document
from overgraph_ingest.extraction.pdf import extract_pdf

__all__ = [
    "ExtractedDocument",
    "extract_docx",
    "extract_file",
    "extract_pdf",
    "load_extracted",
    "store_extracted",
]


def extract_file(
    data: bytes,
    relative_path: str,
    source_hash: str,
    *,
    extraction_version: str,
) -> ExtractedDocument:
    suffix = relative_path.rsplit(".", 1)[-1].lower()
    if suffix == "pdf":
        return extract_pdf(
            data,
            relative_path,
            source_hash,
            extraction_version=extraction_version,
        )
    if suffix == "docx":
        return extract_docx(
            data,
            relative_path,
            source_hash,
            extraction_version=extraction_version,
        )
    return failed_document(
        relative_path,
        "application/octet-stream",
        source_hash,
        extraction_version,
        f"unsupported file type: {suffix}",
    )
