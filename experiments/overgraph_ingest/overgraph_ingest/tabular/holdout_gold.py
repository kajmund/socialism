"""Holdout question gold. Written before any model run on these documents."""

from __future__ import annotations

from overgraph_ingest.tabular.gold import QUESTION_IDS
from overgraph_ingest.tabular.holdout import HOLD_OUT_DOCUMENTS
from overgraph_ingest.tabular.user_gold import (
    NO,
    SILENT,
    UNTIL_NOTICE,
    YES,
    GoldSpan,
    UserCellGold,
)


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


HOLD_OUT_CELLS: tuple[UserCellGold, ...] = (
    _cell(
        "Avtal_15_Bonusavtal.docx",
        "auto-renewal",
        NO,
        _span("Det förlängs inte automatiskt", "bonusperioden"),
    ),
    _cell("Avtal_15_Bonusavtal.docx", "notice-period", SILENT),
    _cell("Avtal_15_Bonusavtal.docx", "liability-cap", SILENT),
    _cell("Avtal_15_Bonusavtal.docx", "confidentiality", SILENT),
    _cell("Avtal_15_Bonusavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_24_Kopeavtal_fastighet.docx", "auto-renewal", SILENT),
    _cell("Avtal_24_Kopeavtal_fastighet.docx", "notice-period", SILENT),
    _cell(
        "Avtal_24_Kopeavtal_fastighet.docx",
        "liability-cap",
        YES,
        _span(
            "avstår från alla anspråk mot Säljaren på grund av fel i Fastigheten",
            "köparens avstående, även dolda fel",
        ),
        notes="Blankettens ena alternativ. Statutory 4:19 is the other.",
    ),
    _cell("Avtal_24_Kopeavtal_fastighet.docx", "confidentiality", SILENT),
    _cell(
        "Avtal_24_Kopeavtal_fastighet.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Waiver of defect claims. No secrecy exception.",
    ),
    _cell("Avtal_28_Aktieagaravtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_28_Aktieagaravtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_28_Aktieagaravtal.docx",
        "liability-cap",
        SILENT,
        notes="Vite plus damages. Not a limitation.",
    ),
    _cell(
        "Avtal_28_Aktieagaravtal.docx",
        "confidentiality",
        YES,
        _span("hålla innehållet i detta avtal samt information om Bolaget och dess kunder konfidentiellt", "aktieägarna"),
    ),
    _cell("Avtal_28_Aktieagaravtal.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_33_Agentavtal.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("gäller från och med 2024-04-15 och tills vidare", "agentur"),
    ),
    _cell(
        "Avtal_33_Agentavtal.docx",
        "notice-period",
        YES,
        _span("Uppsägningstiden är en (1) månad under det första avtalsåret", "år 1"),
        _span("sex (6) månader under det sjätte och följande år", "år 6+"),
        _span("säga upp avtalet med omedelbar verkan", "väsentligt avtalsbrott"),
    ),
    _cell("Avtal_33_Agentavtal.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_33_Agentavtal.docx",
        "confidentiality",
        YES,
        _span("iaktta sekretess om Huvudmannens affärs- och yrkeshemligheter även efter avtalets upphörande", "agenten"),
    ),
    _cell("Avtal_33_Agentavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_40_Laneavtal_revers.docx",
        "auto-renewal",
        NO,
        _span("förfaller i sin helhet till betalning senast den 2023-06-30", "lånet"),
    ),
    _cell(
        "Avtal_40_Laneavtal_revers.docx",
        "notice-period",
        YES,
        _span("efter minst 30 dagars skriftligt meddelande", "förtida återbetalning"),
        _span("säga upp Lånet till omedelbar betalning", "dröjsmål, obestånd, verksamhetsändring"),
    ),
    _cell("Avtal_40_Laneavtal_revers.docx", "liability-cap", SILENT),
    _cell("Avtal_40_Laneavtal_revers.docx", "confidentiality", SILENT),
    _cell("Avtal_40_Laneavtal_revers.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_43_Leasingavtal_utrustning.docx",
        "auto-renewal",
        NO,
        _span("När leasingperioden löper ut ska DevBrains återlämna Utrustningen", "36 månader"),
        notes="Optional right to extend is not automatic renewal.",
    ),
    _cell(
        "Avtal_43_Leasingavtal_utrustning.docx",
        "notice-period",
        YES,
        _span("kan inte sägas upp i förtid av DevBrains", "leasetagaren"),
        _span("säga upp avtalet med omedelbar verkan", "leasegivaren vid avtalsbrott"),
    ),
    _cell("Avtal_43_Leasingavtal_utrustning.docx", "liability-cap", SILENT),
    _cell("Avtal_43_Leasingavtal_utrustning.docx", "confidentiality", SILENT),
    _cell("Avtal_43_Leasingavtal_utrustning.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_48_Mjukvaruutvecklingsavtal.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_48_Mjukvaruutvecklingsavtal.docx",
        "notice-period",
        YES,
        _span("avbeställa återstående arbete med 30 dagars varsel", "avbeställning"),
        _span("inte har rättats inom 30 dagar får den andra parten häva", "väsentligt avtalsbrott"),
    ),
    _cell(
        "Avtal_48_Mjukvaruutvecklingsavtal.docx",
        "liability-cap",
        YES,
        _span("ansvar för skada är begränsat till [100] procent av takpriset", "tak"),
        _span("Ingen part ansvarar för indirekt skada", "indirekt"),
    ),
    _cell(
        "Avtal_48_Mjukvaruutvecklingsavtal.docx",
        "confidentiality",
        YES,
        _span("hålla den andra partens konfidentiella information hemlig", "parterna"),
    ),
    _cell(
        "Avtal_48_Mjukvaruutvecklingsavtal.docx",
        "liability-secrecy-carveout",
        YES,
        _span("utom vid uppsåt, grov vårdslöshet, brott mot sekretess", "13"),
    ),
    _cell("Avtal_51_Anvandarvillkor_webbplats_app.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_51_Anvandarvillkor_webbplats_app.docx",
        "notice-period",
        YES,
        _span("minst 30 dagar innan de börjar gälla", "väsentliga villkorsändringar"),
        _span("när som helst sluta använda Appen", "användaren"),
    ),
    _cell(
        "Avtal_51_Anvandarvillkor_webbplats_app.docx",
        "liability-cap",
        YES,
        _span("ansvarar inte för indirekta skador eller förlust av data", "indirekt, utom uppsåt/grov"),
    ),
    _cell("Avtal_51_Anvandarvillkor_webbplats_app.docx", "confidentiality", SILENT),
    _cell(
        "Avtal_51_Anvandarvillkor_webbplats_app.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Indirect-loss exclusion. No secrecy exception.",
    ),
    _cell("Avtal_55_Overlatelse_domannamn.docx", "auto-renewal", SILENT),
    _cell("Avtal_55_Overlatelse_domannamn.docx", "notice-period", SILENT),
    _cell("Avtal_55_Overlatelse_domannamn.docx", "liability-cap", SILENT),
    _cell("Avtal_55_Overlatelse_domannamn.docx", "confidentiality", SILENT),
    _cell("Avtal_55_Overlatelse_domannamn.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_58_IT_policy_BYOD.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_58_IT_policy_BYOD.docx",
        "notice-period",
        YES,
        _span("informerat Arbetstagaren minst 30 dagar i förväg", "policyändring"),
    ),
    _cell(
        "Avtal_58_IT_policy_BYOD.docx",
        "liability-cap",
        YES,
        _span("ersätter skada eller förlust endast om den har orsakats genom uppsåt eller grov vårdslöshet", "arbetstagarens utrustning"),
    ),
    _cell(
        "Avtal_58_IT_policy_BYOD.docx",
        "confidentiality",
        YES,
        _span("Konfidentiell information och kunddata får endast lagras i system som DevBrains har godkänt", "lagring"),
    ),
    _cell(
        "Avtal_58_IT_policy_BYOD.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Employee equipment limitation. No secrecy exception.",
    ),
    _cell("Avtal_61_PUB_avtal_DevBrains_ansvarig.docx", "auto-renewal", SILENT),
    _cell("Avtal_61_PUB_avtal_DevBrains_ansvarig.docx", "notice-period", SILENT),
    _cell(
        "Avtal_61_PUB_avtal_DevBrains_ansvarig.docx",
        "liability-cap",
        NO,
        _span("Ansvarsbegränsningar i Huvudavtalet gäller inte för sådan ersättning", "GDPR art. 82"),
    ),
    _cell(
        "Avtal_61_PUB_avtal_DevBrains_ansvarig.docx",
        "confidentiality",
        YES,
        _span("åtagit sig att iaktta konfidentialitet", "biträdets personal"),
    ),
    _cell("Avtal_61_PUB_avtal_DevBrains_ansvarig.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_64_Byraavtal_reklam.docx",
        "auto-renewal",
        YES,
        _span("förlängs därefter med tolv (12) månader i taget", "kalenderår"),
    ),
    _cell(
        "Avtal_64_Byraavtal_reklam.docx",
        "notice-period",
        YES,
        _span("sägs upp senast tre (3) månader före avtalstidens utgång", "förhindra förlängning"),
    ),
    _cell(
        "Avtal_64_Byraavtal_reklam.docx",
        "liability-cap",
        YES,
        _span("begränsat till arvodet under de senaste tolv (12) månaderna", "övrigt ansvar"),
    ),
    _cell(
        "Avtal_64_Byraavtal_reklam.docx",
        "confidentiality",
        YES,
        _span("hålla information om DevBrains, produkter och lanseringsplaner konfidentiell", "byrån"),
    ),
    _cell(
        "Avtal_64_Byraavtal_reklam.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Cap excepts intent and gross negligence only.",
    ),
    _cell("Avtal_67_Evenemangsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_67_Evenemangsavtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_67_Evenemangsavtal.docx",
        "liability-cap",
        YES,
        _span("ansvar är begränsat till priset för evenemanget", "anläggningen"),
    ),
    _cell("Avtal_67_Evenemangsavtal.docx", "confidentiality", SILENT),
    _cell(
        "Avtal_67_Evenemangsavtal.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Event-price cap. No secrecy exception.",
    ),
    _cell("Avtal_71_Konstnarsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_71_Konstnarsavtal.docx", "notice-period", SILENT),
    _cell("Avtal_71_Konstnarsavtal.docx", "liability-cap", SILENT),
    _cell("Avtal_71_Konstnarsavtal.docx", "confidentiality", SILENT),
    _cell("Avtal_71_Konstnarsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell(
        "Avtal_74_Forsakringsavtal.docx",
        "auto-renewal",
        YES,
        _span("förnyas därefter för ett (1) år i taget", "försäkringsperiod"),
    ),
    _cell(
        "Avtal_74_Forsakringsavtal.docx",
        "notice-period",
        YES,
        _span("säga upp försäkringen att upphöra vid försäkringsperiodens slut", "DevBrains"),
        _span("upphör då att gälla 14 dagar efter att uppsägningen skickades", "obetald premie"),
    ),
    _cell(
        "Avtal_74_Forsakringsavtal.docx",
        "liability-cap",
        SILENT,
        notes="Insured amounts are coverage, not a damages cap between the parties.",
    ),
    _cell("Avtal_74_Forsakringsavtal.docx", "confidentiality", SILENT),
    _cell("Avtal_74_Forsakringsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_78_Uppdragsavtal_juridiskt_ombud.docx", "auto-renewal", SILENT),
    _cell(
        "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
        "notice-period",
        YES,
        _span("Klienten får när som helst avsluta uppdraget", "klienten"),
    ),
    _cell(
        "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
        "liability-cap",
        YES,
        _span("Ansvaret är begränsat till [Belopp] kronor per uppdrag", "vårdslöshet"),
    ),
    _cell(
        "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
        "confidentiality",
        YES,
        _span("tystnadsplikt enligt rättegångsbalken och advokatsamfundets regler", "byrån"),
    ),
    _cell(
        "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Cap excepts intent and gross negligence only.",
    ),
    _cell(
        "Avtal_81_VD_anstallningsavtal.docx",
        "auto-renewal",
        UNTIL_NOTICE,
        _span("Avtalet gäller tills vidare", "VD-anställning"),
    ),
    _cell(
        "Avtal_81_VD_anstallningsavtal.docx",
        "notice-period",
        YES,
        _span("Ömsesidig uppsägningstid är sex (6) månader", "ordinarie"),
        _span("avsluta anställningen med omedelbar verkan", "väsentligt avtalsbrott"),
    ),
    _cell("Avtal_81_VD_anstallningsavtal.docx", "liability-cap", SILENT),
    _cell(
        "Avtal_81_VD_anstallningsavtal.docx",
        "confidentiality",
        YES,
        _span("tystnadsplikt om Bolagets affärs- och yrkeshemligheter under och efter anställningen", "VD"),
    ),
    _cell("Avtal_81_VD_anstallningsavtal.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_84_Villkorat_aktieagartillskott.docx", "auto-renewal", SILENT),
    _cell("Avtal_84_Villkorat_aktieagartillskott.docx", "notice-period", SILENT),
    _cell("Avtal_84_Villkorat_aktieagartillskott.docx", "liability-cap", SILENT),
    _cell("Avtal_84_Villkorat_aktieagartillskott.docx", "confidentiality", SILENT),
    _cell("Avtal_84_Villkorat_aktieagartillskott.docx", "liability-secrecy-carveout", SILENT),
    _cell("Avtal_87_Investeringsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_87_Investeringsavtal.docx", "notice-period", SILENT),
    _cell(
        "Avtal_87_Investeringsavtal.docx",
        "liability-cap",
        YES,
        _span("Huvudägarna svarar i andra hand, högst med [Belopp] kronor var", "garantiansvar"),
        _span("kan inte kräva ersättning för krav som understiger [Belopp] kronor", "de minimis"),
    ),
    _cell(
        "Avtal_87_Investeringsavtal.docx",
        "confidentiality",
        YES,
        _span("Avtalets innehåll är konfidentiellt", "investeringen"),
    ),
    _cell(
        "Avtal_87_Investeringsavtal.docx",
        "liability-secrecy-carveout",
        NO,
        notes="Warranty baskets. No secrecy exception.",
    ),
    _cell("Avtal_90_Anslutningsavtal.docx", "auto-renewal", SILENT),
    _cell("Avtal_90_Anslutningsavtal.docx", "notice-period", SILENT),
    _cell("Avtal_90_Anslutningsavtal.docx", "liability-cap", SILENT),
    _cell("Avtal_90_Anslutningsavtal.docx", "confidentiality", SILENT),
    _cell("Avtal_90_Anslutningsavtal.docx", "liability-secrecy-carveout", SILENT),
)


def holdout_cell_map() -> dict[tuple[str, str], UserCellGold]:
    mapping = {(cell.relative_path, cell.question_id): cell for cell in HOLD_OUT_CELLS}
    if len(mapping) != len(QUESTION_IDS) * len(HOLD_OUT_DOCUMENTS):
        raise ValueError("holdout gold is incomplete")
    return mapping


def assert_holdout_gold_complete() -> None:
    wanted = {
        (path, question_id) for path in HOLD_OUT_DOCUMENTS for question_id in QUESTION_IDS
    }
    have = {(cell.relative_path, cell.question_id) for cell in HOLD_OUT_CELLS}
    if have != wanted:
        raise ValueError(f"holdout gold keys differ: missing={wanted - have} extra={have - wanted}")
