from app.schemas.workspace import WorkspaceDocumentTab, WorkspaceState
from app.services.live_speech_stt_terms import (
    keywords_from_text_units,
    parse_keyword_field,
    shown_source_ids,
)


def test_document_terms_lead_and_base_keywords_fill_the_rest() -> None:
    texts = [
        "Aktieägaravtalet reglerar uppsägningstid och uppsägningstid igen.",
        "Fastighetsbildning nämns en gång i beslutet.",
        "Denna mycket korta lag gäller.",
    ]
    keywords = keywords_from_text_units(
        texts,
        base=parse_keyword_field("avtalslagen\nservitut\nuppsägningstid"),
    )
    assert keywords[0] == "uppsägningstid"
    assert "Aktieägaravtalet" in keywords
    assert "Fastighetsbildning" in keywords
    assert "avtalslagen" in keywords
    assert "servitut" in keywords
    assert "gäller" not in keywords
    assert "denna" not in [item.casefold() for item in keywords]


def test_shown_sources_prefer_the_split_panes() -> None:
    state = WorkspaceState(
        documents=[
            WorkspaceDocumentTab(source_id="first"),
            WorkspaceDocumentTab(source_id="second"),
        ],
        split_source_ids=["left", "right"],
    )
    assert shown_source_ids(state) == ["left", "right"]
    assert shown_source_ids(WorkspaceState()) == []
