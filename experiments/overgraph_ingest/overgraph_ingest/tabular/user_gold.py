"""Question-oriented gold for Tabular Review. Not retrieval gold."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.tabular.gold import QUESTION_IDS, SELECTED_DOCUMENTS, USER_QUESTIONS

TABULAR_USER_GOLD_ID = "tabular-user-gold-v1"

YES = "yes"
NO = "no"
UNTIL_NOTICE = "until_notice"
SILENT = "silent"

QUESTION_CONTRACTS = {
    "auto-renewal": {
        "question": USER_QUESTIONS["auto-renewal"],
        "asks": (
            "Whether the agreement continues or starts a new period without "
            "the parties signing a new agreement."
        ),
        "yes": "A later period starts by itself, or an employment converts by itself.",
        "until_notice": "The original term is tills vidare. That is an answer, not silence.",
        "no": "The text says the relation ends on a date or when the work is done.",
        "silent": "The document does not speak to duration or renewal.",
        "not_the_old_gold": (
            "Old notes excluded tills vidare and conversion. The user question does not."
        ),
    },
    "notice-period": {
        "question": USER_QUESTIONS["notice-period"],
        "asks": "Which notice period or periods apply, and to what.",
        "yes": "One or more times, each tagged with what it governs.",
        "no": "The text says the relation ends without notice.",
        "silent": "No notice or end-without-notice language.",
        "not_the_old_gold": (
            "Old gold wanted a standing terminate-the-agreement term. "
            "Notice that stops auto-renewal, optional early exit, and "
            "immediate end of a framework also answer the user."
        ),
    },
    "liability-cap": {
        "question": USER_QUESTIONS["liability-cap"],
        "asks": "Whether the parties' damages liability is limited, how, and with what exceptions.",
        "yes": "A monetary cap and/or an exclusion of a class of loss.",
        "silent": (
            "Vite, insurance, settlement release, and statutory allocation "
            "are not a limitation of damages liability."
        ),
        "not_the_old_gold": "The user asked about limitation, not only a named cap clause.",
    },
    "confidentiality": {
        "question": USER_QUESTIONS["confidentiality"],
        "asks": "Whether this agreement creates a duty to keep information secret, who, and for how long.",
        "yes": "An operative duty. Several duties in one document are all acceptable.",
        "silent": "A pointer that another agreement already has a duty is not a duty here.",
        "not_the_old_gold": (
            "Old relevant_units omitted some operative NDAs. Absence there is not a no."
        ),
    },
    "liability-secrecy-carveout": {
        "question": USER_QUESTIONS["liability-secrecy-carveout"],
        "asks": (
            "Whether a liability limitation excludes a secrecy breach, "
            "and which provision says so."
        ),
        "yes": "The limitation lists secrecy (or the secrecy undertaking) as an exception.",
        "no": "There is a limitation and it does not mention secrecy.",
        "silent": "There is no limitation to carve out from.",
        "not_the_old_gold": "This question already matched the old gold relation.",
    },
}

# A table cell may list several structured answers, each with its own
# citation. The runner still emits one excerpt today. That is a product
# gap, not a reason to force a single gold span.
CELL_MAY_HAVE_MULTIPLE_ANSWERS = True


@dataclass(frozen=True)
class GoldSpan:
    contains: str
    applies_to: str = ""


@dataclass(frozen=True)
class UserCellGold:
    relative_path: str
    question_id: str
    polarity: str
    answers: tuple[GoldSpan, ...]
    notes: str = ""

    @property
    def addresses(self) -> bool:
        return self.polarity != SILENT or bool(self.answers)


def _cell(
    relative_path: str,
    question_id: str,
    polarity: str,
    *answers: GoldSpan,
    notes: str = "",
) -> UserCellGold:
    return UserCellGold(relative_path, question_id, polarity, answers, notes)


def _span(contains: str, applies_to: str = "") -> GoldSpan:
    return GoldSpan(contains, applies_to)


USER_CELLS: tuple[UserCellGold, ...] = (
    _cell(
        "Avtal_17_Hyresavtal_lokal.docx",
        "auto-renewal",
        YES,
        _span("förlängs det med [tre (3)] år i taget", "hyrestid"),
    ),
    _cell(
        "Avtal_17_Hyresavtal_lokal.docx",
        "notice-period",
        YES,
        _span("sägas upp senast [nio (9)] månader före hyrestidens utgång", "förhindra förlängning"),
        _span("kan säga upp avtalet i förtid", "förverkande"),
    ),
    _cell(
        "Avtal_17_Hyresavtal_lokal.docx",
        "liability-cap",
        YES,
        _span(
            "Hyresvärden ansvarar inte för Hyresgästens förlust på grund av driftavbrott",
            "hyresvärdens driftavbrott utan vårdslöshet",
        ),
    ),
    _cell("Avtal_17_Hyresavtal_lokal.docx", "confidentiality", SILENT),
    _cell(
        "Avtal_17_Hyresavtal_lokal.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Narrow landlord disclaimer. No secrecy exception.",
    ),
    _cell(
        "Avtal_18_Hyresavtal_bostad.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("gäller tills vidare", "alternativ A, operativt"),
        _span("förlängs avtalet tills vidare", "alternativ B i samma blankett"),
        notes="Both alternatives are in the signed text. Tills vidare answers the user.",
    ),
    _cell(
        "Avtal_18_Hyresavtal_bostad.docx",
        "notice-period",
        YES,
        _span("Uppsägningstiden är tre (3) månader för båda parter", "tills vidare"),
        _span("senast tre månader före hyrestidens utgång", "bestämd tid"),
    ),
    _cell(
        "Avtal_18_Hyresavtal_bostad.docx",
        "liability-cap",
        SILENT,
        notes="Tenant pays for own negligence. That is allocation, not a cap.",
    ),
    _cell("Avtal_18_Hyresavtal_bostad.docx", "confidentiality", SILENT),
    _cell("Avtal_18_Hyresavtal_bostad.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("tillsvidareanställning enligt 4 §", "anställningsform"),
        notes="Original term is open-ended. Not a later period.",
    ),
    _cell(
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        "notice-period",
        YES,
        _span("Uppsägningstiden följer 11 § LAS", "lagstadgad skala"),
        _span("För Arbetstagaren är den en (1) månad", "arbetstagaren"),
        _span("6 månader", "arbetsgivaren efter 10 år"),
    ),
    _cell("Avtal_01_Tillsvidareanstallningsavtal.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        "confidentiality",
        YES,
        _span("obehörigen röja eller använda Arbetsgivarens företagshemligheter", "under och efter"),
    ),
    _cell("Avtal_01_Tillsvidareanstallningsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_05_Konsultavtal.docx",
        "auto-renewal",
        NO,
        _span("pågår till och med den", "fast slutdag"),
        _span("tills Uppdraget är slutfört", "alternativ slut"),
    ),
    _cell(
        "Avtal_05_Konsultavtal.docx",
        "notice-period",
        YES,
        _span("säga upp avtalet med [30] dagars uppsägningstid", "ordinarie"),
        _span("häva avtalet med omedelbar verkan", "väsentligt avtalsbrott"),
    ),
    _cell(
        "Avtal_05_Konsultavtal.docx",
        "liability-cap",
        YES,
        _span("Ansvaret är begränsat till [100 %] av det totala arvodet", "direkt skada"),
        _span("Ingen part ansvarar för indirekt skada eller följdskada", "indirekt skada"),
    ),
    _cell(
        "Avtal_05_Konsultavtal.docx",
        "confidentiality",
        YES,
        _span("hålla Konfidentiell information hemlig under avtalstiden och i [fem (5)] år", "konsulten"),
    ),
    _cell(
        "Avtal_05_Konsultavtal.docx",
        "liability-secrecy-carveout",
        YES,
        _span("inte vid uppsåt, grov vårdslöshet eller brott mot sekretessåtagandet", "10.1"),
    ),
    _cell(
        "Avtal_22_Kontorshotell_coworking.docx",
        "auto-renewal",
        YES,
        _span("förlängs därefter med [en (1)] månad i taget", "efter första perioden"),
    ),
    _cell(
        "Avtal_22_Kontorshotell_coworking.docx",
        "notice-period",
        YES,
        _span("sägas upp av båda parter med [en (1)] månads uppsägningstid", "ordinarie"),
        _span("säga upp avtalet så att det upphör samtidigt som höjningen", "prishöjning över 5 %"),
    ),
    _cell(
        "Avtal_22_Kontorshotell_coworking.docx",
        "liability-cap",
        YES,
        _span("ansvar är begränsat till ett belopp som motsvarar [tre (3)] månadsavgifter", "tak"),
        _span("ansvarar inte för indirekt skada, dataförlust", "indirekt skada"),
    ),
    _cell(
        "Avtal_22_Kontorshotell_coworking.docx",
        "confidentiality",
        YES,
        _span("behandla information om DevBrains och dess kunder konfidentiellt", "leverantören"),
    ),
    _cell(
        "Avtal_22_Kontorshotell_coworking.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Cap and indirect exclusion. No secrecy exception.",
    ),
    _cell(
        "Avtal_25_Fastighetsservice_stadning.docx",
        "auto-renewal",
        YES,
        _span("förlängs därefter med [ett (1)] år i taget", "årsvis"),
    ),
    _cell(
        "Avtal_25_Fastighetsservice_stadning.docx",
        "notice-period",
        YES,
        _span("sägs upp senast [tre (3)] månader före avtalstidens utgång", "förhindra förlängning"),
        _span("säga upp avtalet med omedelbar verkan", "väsentligt avtalsbrott"),
    ),
    _cell(
        "Avtal_25_Fastighetsservice_stadning.docx",
        "liability-cap",
        YES,
        _span(
            "Ansvaret för ren förmögenhetsskada och indirekt skada är begränsat till [Belopp] kronor",
            "ren förmögenhet och indirekt",
        ),
    ),
    _cell(
        "Avtal_25_Fastighetsservice_stadning.docx",
        "confidentiality",
        YES,
        _span("Personalen får inte ta del av handlingar, datorer eller skärmar", "personal"),
        _span("personalen har undertecknat en sekretessförbindelse", "förbindelse"),
    ),
    _cell(
        "Avtal_25_Fastighetsservice_stadning.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Cap excepts intent and gross negligence only.",
    ),
    _cell(
        "Avtal_02_Provanstallningsavtal.docx",
        "auto-renewal",
        YES,
        _span("övergår anställningen automatiskt i en tillsvidareanställning", "provtid"),
    ),
    _cell(
        "Avtal_02_Provanstallningsavtal.docx",
        "notice-period",
        YES,
        _span("avbryta provanställningen före provtidens utgång", "under provtid"),
        _span("lämna besked om detta minst två veckor i förväg", "inför provtidens slut"),
        _span("gäller uppsägningstid enligt 11 § LAS", "efter övergång"),
    ),
    _cell("Avtal_02_Provanstallningsavtal.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_02_Provanstallningsavtal.docx",
        "confidentiality",
        YES,
        _span("tystnadsplikt om Arbetsgivarens företagshemligheter", "under och efter"),
    ),
    _cell("Avtal_02_Provanstallningsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_03_Visstidsanstallning.docx",
        "auto-renewal",
        NO,
        _span("upphör utan föregående uppsägning när den avtalade tiden löper ut", "visstid"),
    ),
    _cell(
        "Avtal_03_Visstidsanstallning.docx",
        "notice-period",
        YES,
        _span("upphör utan föregående uppsägning när den avtalade tiden löper ut", "vid tidens utgång"),
        _span("säga upp anställningen i förtid med [en (1) månads] uppsägningstid", "valfri förtida rätt"),
    ),
    _cell("Avtal_03_Visstidsanstallning.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_03_Visstidsanstallning.docx",
        "confidentiality",
        YES,
        _span("tystnadsplikt om Arbetsgivarens företagshemligheter", "under och efter"),
    ),
    _cell("Avtal_03_Visstidsanstallning.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_30_Ramavtal_tjanster.docx",
        "auto-renewal",
        YES,
        _span("förlängs därefter med [tolv (12)] månader i taget", "ramavtal"),
    ),
    _cell(
        "Avtal_30_Ramavtal_tjanster.docx",
        "notice-period",
        YES,
        _span("sägs upp senast [sex (6)] månader före avtalstidens utgång", "förhindra förlängning"),
        _span("säga upp avtalet med omedelbar verkan", "väsentligt avtalsbrott"),
    ),
    _cell(
        "Avtal_30_Ramavtal_tjanster.docx",
        "liability-cap",
        YES,
        _span("Ingen part ansvarar för indirekt skada", "indirekt"),
        _span("sammanlagda ansvar per kalenderår är begränsat", "årligt tak"),
    ),
    _cell(
        "Avtal_30_Ramavtal_tjanster.docx",
        "confidentiality",
        YES,
        _span("hålla den andra partens konfidentiella information hemlig under avtalstiden och i fem (5) år", "parterna"),
    ),
    _cell(
        "Avtal_30_Ramavtal_tjanster.docx",
        "liability-secrecy-carveout",
        YES,
        _span("gäller inte vid uppsåt, grov vårdslöshet, brott mot sekretess", "13.4"),
    ),
    _cell(
        "Avtal_36_Underleverantorsavtal.docx",
        "auto-renewal",
        NO,
        _span("gäller från undertecknandet till dess att Uppdraget har slutförts", "uppdragets slut"),
    ),
    _cell(
        "Avtal_36_Underleverantorsavtal.docx",
        "notice-period",
        YES,
        _span("avbeställa Uppdraget med [30] dagars varsel", "om huvudavtalet upphör"),
        _span("häva avtalet om rättelse inte har skett inom 14 dagar", "väsentligt avtalsbrott"),
    ),
    _cell(
        "Avtal_36_Underleverantorsavtal.docx",
        "liability-cap",
        YES,
        _span("ansvar är begränsat till [två (2)] gånger den totala ersättningen", "tak"),
    ),
    _cell(
        "Avtal_36_Underleverantorsavtal.docx",
        "confidentiality",
        YES,
        _span("hålla information om DevBrains, Slutkunden och Uppdraget konfidentiell", "under och fem år"),
    ),
    _cell(
        "Avtal_36_Underleverantorsavtal.docx",
        "liability-secrecy-carveout",
        YES,
        _span("utom vid uppsåt, grov vårdslöshet eller brott mot sekretess", "10.2"),
    ),
    _cell(
        "Avtal_04_Timanstallning_behovsanstallning.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("gäller från och med den [2022-06-01] tills vidare", "ramavtal"),
        notes="Each shift ends by itself. The framework continues until notice.",
    ),
    _cell(
        "Avtal_04_Timanstallning_behovsanstallning.docx",
        "notice-period",
        YES,
        _span("säga upp ramavtalet med omedelbar verkan", "ramavtal"),
        _span("upphör utan uppsägning när passet är slut", "enskilt pass"),
    ),
    _cell("Avtal_04_Timanstallning_behovsanstallning.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_04_Timanstallning_behovsanstallning.docx",
        "confidentiality",
        YES,
        _span("tystnadsplikt om Arbetsgivarens företagshemligheter", "arbetstagaren"),
    ),
    _cell("Avtal_04_Timanstallning_behovsanstallning.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", "auto-renewal", SILENT),
    _cell("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", "notice-period", SILENT),
    _cell(
        "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
        "liability-cap",
        SILENT,
        notes="Vite plus damages above the vite expands liability. It is not a cap.",
    ),
    _cell(
        "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
        "confidentiality",
        YES,
        _span("hålla Konfidentiell Information hemlig", "mottagaren"),
        _span("Sekretesskyldigheten gäller i [fem (5)] år från det att informationen lämnades ut", "varaktighet"),
    ),
    _cell("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_07_Sekretessavtal_omsesidigt.docx", "auto-renewal", SILENT),
    _cell("Avtal_07_Sekretessavtal_omsesidigt.docx", "notice-period", SILENT),
    _cell(
        "Avtal_07_Sekretessavtal_omsesidigt.docx",
        "liability-cap",
        SILENT,
        notes="Damages and optional vite. Not a limitation.",
    ),
    _cell(
        "Avtal_07_Sekretessavtal_omsesidigt.docx",
        "confidentiality",
        YES,
        _span("hålla Konfidentiell Information hemlig och inte röja den för tredje man", "ömsesidigt"),
        _span("Sekretesskyldigheten gäller i [fem (5)] år efter avtalets upphörande", "varaktighet"),
    ),
    _cell("Avtal_07_Sekretessavtal_omsesidigt.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_08_Konkurrensforbudsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_08_Konkurrensforbudsavtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_08_Konkurrensforbudsavtal.docx",
        "liability-cap",
        SILENT,
        notes="Vite is a sanction.",
    ),
    _cell(
        "Avtal_08_Konkurrensforbudsavtal.docx",
        "confidentiality",
        SILENT,
        notes="Says this agreement does not affect an existing duty. No duty is created here.",
    ),
    _cell("Avtal_08_Konkurrensforbudsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "auto-renewal", SILENT),
    _cell("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "notice-period", SILENT),
    _cell(
        "Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx",
        "liability-cap",
        SILENT,
        notes="Vite is a sanction, not a limitation of damages.",
    ),
    _cell("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "confidentiality", SILENT),
    _cell("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_100_Djurkopeavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_100_Djurkopeavtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_100_Djurkopeavtal.docx",
        "liability-cap",
        SILENT,
        notes="Consumer remedies are not a damages cap.",
    ),
    _cell("Avtal_100_Djurkopeavtal.docx", "confidentiality", SILENT),
    _cell("Avtal_100_Djurkopeavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_10_Arbetstidsavtal_flextid.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_10_Arbetstidsavtal_flextid.docx",
        "notice-period",
        YES,
        _span("minst [en månads] varsel", "avsluta flextid"),
        _span("säga upp detta tilläggsavtal med [en månads] varsel", "tillägget"),
    ),
    _cell("Avtal_10_Arbetstidsavtal_flextid.docx", "liability-cap", SILENT),
    _cell("Avtal_10_Arbetstidsavtal_flextid.docx", "confidentiality", SILENT),
    _cell("Avtal_10_Arbetstidsavtal_flextid.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_11_Distansarbetsavtal.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("gäller från och med den [2020-09-01] tills vidare", "tillägget"),
    ),
    _cell(
        "Avtal_11_Distansarbetsavtal.docx",
        "notice-period",
        YES,
        _span("säga upp avtalet med [en (1)] månads uppsägningstid", "tillägget, inte anställningen"),
    ),
    _cell("Avtal_11_Distansarbetsavtal.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_11_Distansarbetsavtal.docx",
        "confidentiality",
        YES,
        _span("Konfidentiella handlingar ska förvaras så att obehöriga inte kan ta del av dem", "distans"),
        _span("inte låta obehöriga använda utrustningen", "utrustning"),
    ),
    _cell("Avtal_11_Distansarbetsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
        "notice-period",
        YES,
        _span("Din uppsägningstid är [antal] månader", "uppsägningsbeskedet"),
    ),
    _cell(
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
        "liability-cap",
        SILENT,
        notes="Final settlement of employment claims is not a damages cap.",
    ),
    _cell("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx", "confidentiality", SILENT),
    _cell("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_13_Avgangsvederlagsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_13_Avgangsvederlagsavtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_13_Avgangsvederlagsavtal.docx",
        "liability-cap",
        SILENT,
        notes="Release of further employment claims is not a damages cap.",
    ),
    _cell(
        "Avtal_13_Avgangsvederlagsavtal.docx",
        "confidentiality",
        YES,
        _span("fortsatt tystnadsplikt om Arbetsgivarens företagshemligheter", "6.1"),
        _span("Innehållet i detta avtal är konfidentiellt", "6.3"),
        notes="Both duties answer the user. Old gold counted only 6.1.",
    ),
    _cell("Avtal_13_Avgangsvederlagsavtal.docx", "liability-secrecy-carveout", SILENT),
)


def user_cell_map() -> dict[tuple[str, str], UserCellGold]:
    mapping = {(cell.relative_path, cell.question_id): cell for cell in USER_CELLS}
    if len(mapping) != len(QUESTION_IDS) * len(SELECTED_DOCUMENTS):
        raise ValueError("tabular user gold is incomplete")
    return mapping


def assert_user_gold_complete() -> None:
    wanted = {(path, question_id) for path in SELECTED_DOCUMENTS for question_id in QUESTION_IDS}
    have = {(cell.relative_path, cell.question_id) for cell in USER_CELLS}
    if have != wanted:
        raise ValueError(f"user gold keys differ: missing={wanted - have} extra={have - wanted}")
    unknown = {cell.polarity for cell in USER_CELLS} - {YES, NO, UNTIL_NOTICE, SILENT}
    if unknown:
        raise ValueError(f"unknown polarity: {unknown}")
    if set(QUESTION_CONTRACTS) != set(QUESTION_IDS):
        raise ValueError("question contracts do not match question ids")
