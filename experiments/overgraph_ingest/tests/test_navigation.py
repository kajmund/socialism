from overgraph_ingest.navigation.hop import (
    child_clause_hops,
    is_heading_unit,
    referenced_clause_hops,
    section_hops,
)
from overgraph_ingest.retrieval.index import StoredUnit


def _unit(key: str, text: str, structure_id: str, sequence: int) -> StoredUnit:
    return StoredUnit(
        node_id=sequence,
        key=key,
        document_id="doc-46",
        relative_path="Avtal_46_SaaS_avtal.docx",
        text=text,
        dense=None,
        sparse=None,
        structure_id=structure_id,
        sequence=sequence,
    )


def test_section_hop_finds_the_cap_without_relabeling_the_start() -> None:
    start = _unit(
        "carve",
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess.",
        "s-12-4",
        4,
    )
    cap = _unit(
        "cap",
        "DevBrains sammanlagda ansvar per avtalsår är begränsat till de avgifter "
        "som Kunden har betalat under de senaste tolv (12) månaderna.",
        "s-12-3",
        3,
    )
    other = _unit("later", "13. Sekretess Parterna ska hålla information hemlig.", "s-13", 5)
    structures = {
        "s-12-3": {"parent_id": "s-12", "clause_number": "12.3", "title": "12.3 Cap"},
        "s-12-4": {"parent_id": "s-12", "clause_number": "12.4", "title": "12.4 Carve-out"},
        "s-13": {"parent_id": "root", "clause_number": "13", "title": "13. Sekretess"},
    }
    hops = section_hops(start, [start, cap, other], structures)
    assert any(hop.key == "cap" and hop.relation in {"PREVIOUS", "SAME_SECTION"} for hop in hops)
    assert all(hop.key != "carve" for hop in hops)
    next_hop = next(hop for hop in hops if hop.key == "later")
    assert next_hop.relation == "NEXT"


def test_punkt_reference_skips_table_cells_named_four() -> None:
    start = StoredUnit(
        1,
        "start",
        "doc-49",
        "Avtal_49_IT_drift_hostingavtal.docx",
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4.",
        None,
        None,
        "s-6-3",
        10,
    )
    heading = StoredUnit(
        2,
        "heading",
        "doc-49",
        "Avtal_49_IT_drift_hostingavtal.docx",
        "4. Informationssäkerhet och dataskydd",
        None,
        None,
        "s-4",
        4,
    )
    child = StoredUnit(
        4,
        "child",
        "doc-49",
        "Avtal_49_IT_drift_hostingavtal.docx",
        "4.1 Leverantören ska ha ett ledningssystem för informationssäkerhet.",
        None,
        None,
        "s-4-1",
        5,
    )
    table = StoredUnit(
        3,
        "table",
        "doc-49",
        "Avtal_49_IT_drift_hostingavtal.docx",
        "4 timmar",
        None,
        None,
        "s-table",
        2,
    )
    structures = {
        "s-6-3": {"parent_id": "s-6", "clause_number": "6.3", "title": "6.3 Begränsningarna"},
        "s-4": {
            "parent_id": "root",
            "clause_number": "4",
            "title": "4. Informationssäkerhet och dataskydd",
        },
        "s-4-1": {
            "parent_id": "root",
            "clause_number": "4.1",
            "title": "4.1 Leverantören ska ha ett ledningssystem för informationssäkerhet.",
        },
        "s-table": {"parent_id": None, "clause_number": "4", "title": "4 timmar"},
    }
    reference, hops = referenced_clause_hops(start, [start, heading, child, table], structures)
    assert reference == "4"
    assert [hop.key for hop in hops] == ["heading", "child"]
    assert hops[0].relation == "CLAUSE_4"


def test_heading_navigates_to_children_not_siblings() -> None:
    heading = _unit("h", "4. Avtalstid och uppsägning\n", "s-4", 1)
    child = _unit("c", "4.1 Avtalet förlängs därefter med en månad i taget.", "s-4-1", 2)
    sibling = _unit("s", "5. Avgift", "s-5", 3)
    structures = {
        "s-4": {"parent_id": "root", "clause_number": "4", "title": "4. Avtalstid och uppsägning"},
        "s-4-1": {"parent_id": "s-4", "clause_number": "4.1", "title": "4.1 Förlängning"},
        "s-5": {"parent_id": "root", "clause_number": "5", "title": "5. Avgift"},
    }
    assert is_heading_unit(heading, structures)
    hops = child_clause_hops(heading, [heading, child, sibling], structures)
    assert [hop.key for hop in hops] == ["c"]
    assert hops[0].relation == "CHILD"
