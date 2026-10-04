"""DOCX exports from immutable revisions, with the same citation numbers as chat."""

from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from app.database.workspace_models import WorkspaceArtifactRevision, WorkspaceReference

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", WORD_NS)


def _element(parent: ET.Element, name: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{WORD_NS}}}{name}", {f"{{{WORD_NS}}}{key}": value for key, value in attrs.items()})


def _paragraph(body: ET.Element, text: str, *, heading: bool = False) -> None:
    paragraph = _element(body, "p")
    properties = _element(paragraph, "pPr")
    _element(properties, "spacing", after="160")
    if heading:
        _element(properties, "keepNext")
    run = _element(paragraph, "r")
    run_properties = _element(run, "rPr")
    _element(run_properties, "rFonts", ascii="Calibri", hAnsi="Calibri")
    _element(run_properties, "sz", val="28" if heading else "22")
    if heading:
        _element(run_properties, "b")
    for index, line in enumerate(text.split("\n")):
        if index:
            _element(run, "br")
        content = _element(run, "t")
        content.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        content.text = line


def export_revision_docx(revision: WorkspaceArtifactRevision, references: list[WorkspaceReference]) -> bytes:
    """Produce a Word-readable OOXML package without an extra runtime dependency."""
    by_id = {reference.id: reference for reference in references}
    used: set[str] = set()
    document = ET.Element(f"{{{WORD_NS}}}document")
    body = _element(document, "body")
    _paragraph(body, revision.title, heading=True)
    for block in revision.content["blocks"]:
        refs = block.get("source_refs", [])
        used.update(refs)
        suffix = " ".join(f"[{by_id[reference_id].number}]" for reference_id in refs)
        text = block["text"] + (f" {suffix}" if suffix else "")
        _paragraph(body, text, heading=block["type"] == "heading")
    if used:
        _paragraph(body, "Källor / Sources", heading=True)
        for reference in sorted((by_id[value] for value in used), key=lambda row: row.number):
            snapshot = reference.snapshot
            title = str(snapshot.get("title") or snapshot.get("filename") or reference.source_id)
            anchor = reference.anchor
            location = str(anchor.get("label") or anchor.get("locator") or "")
            page = anchor.get("page_number")
            if page is not None:
                location = f"{location} · s. {page}" if location else f"s. {page}"
            source_url = str(snapshot.get("source_url") or "")
            details = " · ".join(value for value in (title, location, source_url, f"version {reference.source_version}") if value)
            _paragraph(body, f"[{reference.number}] {details}")
    section = _element(body, "sectPr")
    _element(section, "pgSz", w="11906", h="16838")
    _element(section, "pgMar", top="1134", right="1134", bottom="1134", left="1134")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        package.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
    return output.getvalue()
