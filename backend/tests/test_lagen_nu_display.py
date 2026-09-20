from app.services.lagen_nu.display import (
    choose_legal_excerpt,
    citation_from_lagen_nu_uri,
    display_source_title,
    is_legal_front_matter,
    relevant_legal_excerpt,
    selector_passage_text,
)


def test_citation_from_proposition_and_sfs_uris():
    assert citation_from_lagen_nu_uri("https://lagen.nu/prop/1975:6") == "Prop. 1975:6"
    assert (
        citation_from_lagen_nu_uri("https://lagen.nu/prop/1975/76:81#a38-2")
        == "Prop. 1975/76:81"
    )
    assert citation_from_lagen_nu_uri("https://lagen.nu/sou/2014:22") == "SOU 2014:22"
    assert citation_from_lagen_nu_uri("https://lagen.nu/1999:1078#K2P4") == "SFS 1999:1078"
    assert (
        citation_from_lagen_nu_uri("https://lagen.nu/dom/nja/2014s877")
        == "NJA 2014 s. 877"
    )


def test_proposition_title_uses_citation_not_cover_page():
    title = display_source_title(
        uri="https://lagen.nu/prop/1975:6",
        identifier="Prop. 1975:6",
        title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
    )
    assert title == "Prop. 1975:6 — Ändring i konkurslagen (1921:225)"


def test_law_title_keeps_official_name():
    title = display_source_title(
        uri="https://lagen.nu/1915:218#P36",
        identifier="SFS 1915:218",
        title="Lag (1915:218) om avtal",
    )
    assert title == "Lag (1915:218) om avtal"


def test_proposition_cover_page_is_front_matter():
    excerpt = (
        "Regeringens proposition nr 6 år 1975 Prop. 1975:6 Nr 6 "
        "Regeringens proposition om ändring i konkurslagen (1921:225) m.m.; "
        "beslutad den 16 januari 1975."
    )
    assert is_legal_front_matter(
        excerpt,
        title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
    )
    body = (
        "Kungl. Maj:t föreslår riksdagen att anta ett nytt obeståndsbegrepp "
        "som knyter konkursförutsättningen till gäldenärens betalningsoförmåga."
    )
    assert not is_legal_front_matter(body)


def test_relevant_excerpt_skips_cover_page_for_body_text():
    text = (
        "Regeringens proposition nr 6 år 1975\n"
        "Prop. 1975:6\n"
        "Nr 6\n"
        "Regeringens proposition om ändring i konkurslagen (1921:225) m.m.; "
        "beslutad den 16 januari 1975.\n\n"
        "Kungl. Maj:t föreslår riksdagen att anta ett nytt obeståndsbegrepp "
        "som knyter konkursförutsättningen till gäldenärens betalningsoförmåga."
    )
    excerpt = relevant_legal_excerpt(
        text,
        terms=frozenset({"obestånd", "konkurslagen"}),
        title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
    )
    assert "obeståndsbegrepp" in excerpt
    assert "beslutad den 16 januari 1975" not in excerpt


def test_choose_legal_excerpt_rejects_header_highlight():
    excerpt = choose_legal_excerpt(
        document_text=(
            "Regeringens proposition nr 6 år 1975 Prop. 1975:6\n\n"
            "Obestånd föreligger när gäldenären inte kan betala sina skulder "
            "och denna oförmåga inte är endast tillfällig."
        ),
        hit_excerpt="Regeringens proposition nr 6 år 1975",
        terms=frozenset({"obestånd", "gäldenären"}),
        title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
        max_chars=16000,
    )
    assert excerpt.startswith("Obestånd föreligger")


def test_huvudsakligt_innehall_is_front_matter():
    summary = (
        "Huvudsakligt innehåll Propositionen föreslår en generalklausul "
        "i avtalslagen som ger domstolen rätt att jämka oskäliga villkor."
    )
    assert is_legal_front_matter(summary)
    body = (
        "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
        "avtalets innehåll, omständigheterna vid avtalets tillkomst och "
        "omständigheterna i övrigt."
    )
    excerpt = relevant_legal_excerpt(
        f"{summary}\n\n{body}",
        terms=frozenset({"36 §", "avtalslagen"}),
    )
    assert "36 § avtalslagen" in excerpt
    assert "Huvudsakligt innehåll" not in excerpt


def test_selector_passage_text_windows_around_the_provision():
    text = (
        "Propositionens huvudsakliga innehåll Propositionen föreslår en "
        "generalklausul så att oskäliga villkor kan jämkas.\n\n"
        + ("Övergångsbestämmelser utan bedömningsfaktorer. " * 40)
        + "\n\n"
        "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
        "avtalets innehåll och omständigheterna vid avtalets tillkomst."
    )
    passage = selector_passage_text(
        text,
        needles=frozenset({"36 §", "jämk", "oskälig"}),
        title="Prop. 1975/76:81",
        max_chars=24000,
    )
    assert "36 § avtalslagen" in passage
    assert "Propositionens huvudsakliga innehåll" not in passage
