"""Document-type gold. Locked before any Jev run. Principal function only."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.doctype.taxonomy import (
    CONSULTING,
    DOCUMENT_TYPES,
    DPA,
    EMPLOYMENT,
    LEASE,
    NDA,
    OTHER,
    SUPPLY,
    TERMINATION,
    require_type,
)
from overgraph_ingest.tabular.holdout import published_contracts

GOLD_ID = "doctype-gold-v1"

DOCUMENTS = (
    "Avtal_01_Tillsvidareanstallningsavtal.docx",
    "Avtal_02_Provanstallningsavtal.docx",
    "Avtal_03_Visstidsanstallning.docx",
    "Avtal_04_Timanstallning_behovsanstallning.docx",
    "Avtal_05_Konsultavtal.docx",
    "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
    "Avtal_07_Sekretessavtal_omsesidigt.docx",
    "Avtal_08_Konkurrensforbudsavtal.docx",
    "Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx",
    "Avtal_10_Arbetstidsavtal_flextid.docx",
    "Avtal_11_Distansarbetsavtal.docx",
    "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
    "Avtal_13_Avgangsvederlagsavtal.docx",
    "Avtal_14_Tjanstebilsavtal.docx",
    "Avtal_15_Bonusavtal.docx",
    "Avtal_16_Praktikavtal.docx",
    "Avtal_17_Hyresavtal_lokal.docx",
    "Avtal_18_Hyresavtal_bostad.docx",
    "Avtal_19_Andrahandsuthyrning_lokal.docx",
    "Avtal_20_Arrendeavtal_lagenhetsarrende.docx",
    "Avtal_21_Parkeringsavtal.docx",
    "Avtal_22_Kontorshotell_coworking.docx",
    "Avtal_23_Tillaggsavtal_hyresavtal_lokal.docx",
    "Avtal_24_Kopeavtal_fastighet.docx",
    "Avtal_25_Fastighetsservice_stadning.docx",
    "Avtal_26_Stiftelseurkund.docx",
    "Avtal_27_Bolagsordning.docx",
    "Avtal_28_Aktieagaravtal.docx",
    "Avtal_29_Samarbetsavtal.docx",
    "Avtal_30_Ramavtal_tjanster.docx",
    "Avtal_31_Leveransavtal.docx",
    "Avtal_32_Inkopsavtal.docx",
    "Avtal_33_Agentavtal.docx",
    "Avtal_34_Aterforsaljaravtal.docx",
    "Avtal_35_Franchiseavtal.docx",
    "Avtal_36_Underleverantorsavtal.docx",
    "Avtal_37_Allmanna_villkor_B2B.docx",
    "Avtal_38_Projektavtal_fast_pris.docx",
    "Avtal_39_Avsiktsforklaring_LOI.docx",
    "Avtal_40_Laneavtal_revers.docx",
    "Avtal_41_Borgensforbindelse.docx",
    "Avtal_42_Factoringavtal.docx",
    "Avtal_43_Leasingavtal_utrustning.docx",
    "Avtal_44_Avbetalningsplan.docx",
    "Avtal_45_Fullmakt.docx",
    "Avtal_46_SaaS_avtal.docx",
    "Avtal_47_Programvarulicensavtal.docx",
    "Avtal_48_Mjukvaruutvecklingsavtal.docx",
    "Avtal_49_IT_drift_hostingavtal.docx",
    "Avtal_50_Support_underhallsavtal.docx",
    "Avtal_51_Anvandarvillkor_webbplats_app.docx",
    "Avtal_52_Licensavtal_varumarke.docx",
    "Avtal_53_Overlatelse_immateriella_rattigheter.docx",
    "Avtal_54_Kallkodsdeposition_escrow.docx",
    "Avtal_55_Overlatelse_domannamn.docx",
    "Avtal_56_Bidragsavtal_CLA.docx",
    "Avtal_57_Penetrationstest.docx",
    "Avtal_58_IT_policy_BYOD.docx",
    "Avtal_59_Agilt_IT_konsultavtal.docx",
    "Avtal_60_Pilotavtal_PoC.docx",
    "Avtal_61_PUB_avtal_DevBrains_ansvarig.docx",
    "Avtal_62_PUB_GDPR_databehandlingsavtal.docx",
    "Avtal_63_Appavtal_utveckling_publicering.docx",
    "Avtal_64_Byraavtal_reklam.docx",
    "Avtal_65_Sponsringsavtal.docx",
    "Avtal_66_Foto_filmavtal_bildlicens.docx",
    "Avtal_67_Evenemangsavtal.docx",
    "Avtal_68_Hyresavtal_fordon.docx",
    "Avtal_69_Kundavtal_B2C_villkor.docx",
    "Avtal_70_Offertvillkor_orderbekraftelse.docx",
    "Avtal_71_Konstnarsavtal.docx",
    "Avtal_72_Utbildningsavtal.docx",
    "Avtal_73_Volontaravtal.docx",
    "Avtal_74_Forsakringsavtal.docx",
    "Avtal_75_Visselblasarfunktion.docx",
    "Avtal_76_Uppdragsbrev_revision.docx",
    "Avtal_77_Redovisningsuppdrag.docx",
    "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
    "Avtal_79_Hyresavtal_lokal_Goteborg.docx",
    "Avtal_80_Styrelsens_arbetsordning.docx",
    "Avtal_81_VD_anstallningsavtal.docx",
    "Avtal_82_Uppdragsavtal_styrelseledamot.docx",
    "Avtal_83_Teckningsoptionsavtal.docx",
    "Avtal_84_Villkorat_aktieagartillskott.docx",
    "Avtal_85_Konvertibelt_laneavtal.docx",
    "Avtal_86_Aktieoverlatelseavtal.docx",
    "Avtal_87_Investeringsavtal.docx",
    "Avtal_88_Teckningsavtal_nyemission.docx",
    "Avtal_89_Aktieagaravtal_uppdaterat.docx",
    "Avtal_90_Anslutningsavtal.docx",
    "Avtal_91_Inkramsoverlatelse.docx",
    "Avtal_92_Forlikningsavtal.docx",
    "Avtal_93_Avveckling_av_samarbete.docx",
    "Avtal_94_Kopeavtal_los_egendom.docx",
    "Avtal_95_Gavobrev.docx",
    "Avtal_96_Testamente.docx",
    "Avtal_97_Skuldebrev.docx",
    "Avtal_98_Samboavtal.docx",
    "Avtal_99_Aktenskapsforord.docx",
    "Avtal_100_Djurkopeavtal.docx",
)

NAMED_TYPES = {
    "Avtal_01_Tillsvidareanstallningsavtal.docx": EMPLOYMENT,
    "Avtal_02_Provanstallningsavtal.docx": EMPLOYMENT,
    "Avtal_03_Visstidsanstallning.docx": EMPLOYMENT,
    "Avtal_04_Timanstallning_behovsanstallning.docx": EMPLOYMENT,
    "Avtal_81_VD_anstallningsavtal.docx": EMPLOYMENT,
    "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx": TERMINATION,
    "Avtal_13_Avgangsvederlagsavtal.docx": TERMINATION,
    "Avtal_06_Sekretessavtal_ensidigt_NDA.docx": NDA,
    "Avtal_07_Sekretessavtal_omsesidigt.docx": NDA,
    "Avtal_61_PUB_avtal_DevBrains_ansvarig.docx": DPA,
    "Avtal_62_PUB_GDPR_databehandlingsavtal.docx": DPA,
    "Avtal_05_Konsultavtal.docx": CONSULTING,
    "Avtal_36_Underleverantorsavtal.docx": CONSULTING,
    "Avtal_57_Penetrationstest.docx": CONSULTING,
    "Avtal_59_Agilt_IT_konsultavtal.docx": CONSULTING,
    "Avtal_64_Byraavtal_reklam.docx": CONSULTING,
    "Avtal_66_Foto_filmavtal_bildlicens.docx": CONSULTING,
    "Avtal_75_Visselblasarfunktion.docx": CONSULTING,
    "Avtal_77_Redovisningsuppdrag.docx": CONSULTING,
    "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx": CONSULTING,
    "Avtal_17_Hyresavtal_lokal.docx": LEASE,
    "Avtal_18_Hyresavtal_bostad.docx": LEASE,
    "Avtal_19_Andrahandsuthyrning_lokal.docx": LEASE,
    "Avtal_20_Arrendeavtal_lagenhetsarrende.docx": LEASE,
    "Avtal_21_Parkeringsavtal.docx": LEASE,
    "Avtal_23_Tillaggsavtal_hyresavtal_lokal.docx": LEASE,
    "Avtal_43_Leasingavtal_utrustning.docx": LEASE,
    "Avtal_68_Hyresavtal_fordon.docx": LEASE,
    "Avtal_79_Hyresavtal_lokal_Goteborg.docx": LEASE,
    "Avtal_25_Fastighetsservice_stadning.docx": SUPPLY,
    "Avtal_30_Ramavtal_tjanster.docx": SUPPLY,
    "Avtal_31_Leveransavtal.docx": SUPPLY,
    "Avtal_32_Inkopsavtal.docx": SUPPLY,
    "Avtal_38_Projektavtal_fast_pris.docx": SUPPLY,
    "Avtal_46_SaaS_avtal.docx": SUPPLY,
    "Avtal_48_Mjukvaruutvecklingsavtal.docx": SUPPLY,
    "Avtal_49_IT_drift_hostingavtal.docx": SUPPLY,
    "Avtal_50_Support_underhallsavtal.docx": SUPPLY,
    "Avtal_63_Appavtal_utveckling_publicering.docx": SUPPLY,
}


@dataclass(frozen=True)
class HardCase:
    case_id: str
    left_path: str
    right_path: str
    note: str


HARD_CASES = (
    HardCase(
        "employment_vs_termination_notice",
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
        "Creating employment is not the instrument that ends it.",
    ),
    HardCase(
        "consulting_vs_supply",
        "Avtal_05_Konsultavtal.docx",
        "Avtal_31_Leveransavtal.docx",
        "An independent assignment is not a sale of goods or a finished deliverable.",
    ),
    HardCase(
        "nda_vs_secrecy_clause",
        "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
        "Avtal_05_Konsultavtal.docx",
        "A consulting agreement with secrecy is not an NDA.",
    ),
    HardCase(
        "dpa_vs_main_with_privacy",
        "Avtal_62_PUB_GDPR_databehandlingsavtal.docx",
        "Avtal_46_SaaS_avtal.docx",
        "A SaaS main contract that mentions data protection is not a DPA.",
    ),
    HardCase(
        "employment_vs_termination_settlement",
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        "Avtal_13_Avgangsvederlagsavtal.docx",
        "Severance that ends employment is not the employment agreement.",
    ),
    HardCase(
        "termination_vs_dispute_settlement",
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
        "Avtal_92_Forlikningsavtal.docx",
        "A later settlement of a dispute about a past termination is not the termination instrument.",
    ),
)


def gold_by_path() -> dict[str, str]:
    rows = {path: OTHER for path in DOCUMENTS}
    rows.update(NAMED_TYPES)
    return {path: require_type(document_type) for path, document_type in rows.items()}


def gold_type(relative_path: str) -> str:
    return gold_by_path()[relative_path]


def assert_gold_complete() -> None:
    mapping = gold_by_path()
    if tuple(mapping) != DOCUMENTS:
        raise ValueError("document-type gold paths drifted from the locked 100")
    if len(mapping) != 100:
        raise ValueError(f"document-type gold needs 100 documents, got {len(mapping)}")
    if set(mapping.values()) != set(DOCUMENT_TYPES):
        raise ValueError("document-type gold is missing a taxonomy type")
    if set(NAMED_TYPES) - set(DOCUMENTS):
        raise ValueError("named gold paths are not in the locked 100")
    for case in HARD_CASES:
        if mapping[case.left_path] == mapping[case.right_path]:
            raise ValueError(f"hard case {case.case_id} collapsed to one type")
    if mapping["Avtal_04_Timanstallning_behovsanstallning.docx"] != EMPLOYMENT:
        raise ValueError("each accepted shift is employment")
    if mapping["Avtal_16_Praktikavtal.docx"] != OTHER:
        raise ValueError("internship without employment is not an employment agreement")
    if mapping["Avtal_22_Kontorshotell_coworking.docx"] != OTHER:
        raise ValueError("coworking without exclusive premises is not a lease")
    if mapping["Avtal_76_Uppdragsbrev_revision.docx"] != OTHER:
        raise ValueError("a statutory audit letter is not a consulting agreement")
    if mapping["Avtal_92_Forlikningsavtal.docx"] != OTHER:
        raise ValueError("a dispute settlement is not a termination agreement")
    if mapping["Avtal_100_Djurkopeavtal.docx"] != OTHER:
        raise ValueError("a consumer animal sale is not a commercial supply agreement")


def assert_gold_matches_corpus() -> None:
    assert_gold_complete()
    published = published_contracts()
    if set(DOCUMENTS) != set(published):
        raise ValueError("document-type gold does not match the published extra corpus")
