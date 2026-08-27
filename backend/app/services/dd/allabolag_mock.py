"""Mock allabolag.se client — deterministic, replaceable."""

from __future__ import annotations

import hashlib
import json

from app.services.dd.schemas import DdCandidateCompany, DdSourcingCriteria


_MOCK_POOL: list[dict[str, object]] = [
    {
        "namn": "Nordic Tech Solutions AB",
        "organisationsnummer": "556123-4567",
        "alder_ar": 12,
        "omrade": "Stockholm",
        "resultat": "vinst",
        "omsattning_sek": 48_000_000,
        "anstallda": 34,
        "beskrivning": "B2B mjukvarubolag inom logistik och lagerstyrning.",
    },
    {
        "namn": "Västkust Industri Partner AB",
        "organisationsnummer": "556234-5678",
        "alder_ar": 28,
        "omrade": "Göteborg",
        "resultat": "vinst",
        "omsattning_sek": 120_000_000,
        "anstallda": 85,
        "beskrivning": "Industriell underhållspartner för processindustri.",
    },
    {
        "namn": "Mälardalen Care Group AB",
        "organisationsnummer": "556345-6789",
        "alder_ar": 8,
        "omrade": "Uppsala",
        "resultat": "förlust",
        "omsattning_sek": 22_000_000,
        "anstallda": 41,
        "beskrivning": "Vårdföretag med fokus på hemtjänst och trygghetslarm.",
    },
    {
        "namn": "Skåne Food Logistics AB",
        "organisationsnummer": "556456-7890",
        "alder_ar": 15,
        "omrade": "Malmö",
        "resultat": "vinst",
        "omsattning_sek": 67_000_000,
        "anstallda": 52,
        "beskrivning": "Kylkedja och distribution till dagligvaruhandel.",
    },
    {
        "namn": "Norrland Energi Service AB",
        "organisationsnummer": "556567-8901",
        "alder_ar": 19,
        "omrade": "Umeå",
        "resultat": "vinst",
        "omsattning_sek": 31_000_000,
        "anstallda": 27,
        "beskrivning": "Service och underhåll av vind- och solanläggningar.",
    },
    {
        "namn": "Öresund Digital Commerce AB",
        "organisationsnummer": "556678-9012",
        "alder_ar": 6,
        "omrade": "Malmö",
        "resultat": "förlust",
        "omsattning_sek": 14_000_000,
        "anstallda": 18,
        "beskrivning": "E-handelsplattform för nischade konsumentvaror.",
    },
    {
        "namn": "Bergslagen Maskin AB",
        "organisationsnummer": "556789-0123",
        "alder_ar": 35,
        "omrade": "Örebro",
        "resultat": "vinst",
        "omsattning_sek": 95_000_000,
        "anstallda": 64,
        "beskrivning": "Tillverkning av specialmaskiner till skogsindustrin.",
    },
    {
        "namn": "Capital Finans Revision AB",
        "organisationsnummer": "556890-1234",
        "alder_ar": 22,
        "omrade": "Stockholm",
        "resultat": "vinst",
        "omsattning_sek": 18_000_000,
        "anstallda": 12,
        "beskrivning": "Revisions- och redovisningsbyrå för medelstora bolag.",
    },
    {
        "namn": "Småland Packaging Innovation AB",
        "organisationsnummer": "556901-2345",
        "alder_ar": 11,
        "omrade": "Växjö",
        "resultat": "oavsett",
        "omsattning_sek": 39_000_000,
        "anstallda": 29,
        "beskrivning": "Hållbara förpackningslösningar till livsmedelsindustrin.",
    },
    {
        "namn": "Arctic Marine Components AB",
        "organisationsnummer": "557012-3456",
        "alder_ar": 17,
        "omrade": "Göteborg",
        "resultat": "vinst",
        "omsattning_sek": 54_000_000,
        "anstallda": 38,
        "beskrivning": "Komponentleverantör till marint och offshore.",
    },
]


def _criteria_seed(criteria: DdSourcingCriteria) -> str:
    payload = criteria.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _candidate_id(orgnr: str) -> str:
    return hashlib.sha256(orgnr.encode()).hexdigest()[:16]


def search_companies(criteria: DdSourcingCriteria) -> list[DdCandidateCompany]:
    """Return 5–10 mock candidates matching criteria (deterministic per criteria)."""
    seed = _criteria_seed(criteria)
    rng_byte = int(seed[:2], 16)
    target_count = 5 + (rng_byte % 6)  # 5–10

    filtered: list[dict[str, object]] = []
    for row in _MOCK_POOL:
        alder = int(row["alder_ar"])
        if alder < criteria.alder_min or alder > criteria.alder_max:
            continue
        omrade = str(row["omrade"])
        if criteria.omrade and criteria.omrade.lower() not in omrade.lower():
            continue
        resultat = str(row["resultat"])
        if criteria.resultat != "oavsett" and resultat != criteria.resultat:
            continue
        if criteria.fritext:
            hay = f"{row['namn']} {row['beskrivning']}".lower()
            if criteria.fritext.lower() not in hay:
                continue
        filtered.append(row)

    if not filtered:
        filtered = list(_MOCK_POOL)

    # Deterministic shuffle/order from seed
    ordered = sorted(
        filtered,
        key=lambda r: hashlib.sha256(f"{seed}:{r['organisationsnummer']}".encode()).hexdigest(),
    )

    # Demo minimum: pad with out-of-criteria companies when the filter yields <5 matches.
    # Padded rows are deterministic but may not satisfy the caller's criteria — not silent hits.
    if len(ordered) < 5:
        seen = {str(r["organisationsnummer"]) for r in ordered}
        pool_order = sorted(
            _MOCK_POOL,
            key=lambda r: hashlib.sha256(f"{seed}:pool:{r['organisationsnummer']}".encode()).hexdigest(),
        )
        for row in pool_order:
            orgnr = str(row["organisationsnummer"])
            if orgnr in seen:
                continue
            ordered.append(row)
            seen.add(orgnr)
            if len(ordered) >= 5:
                break

    picked = ordered[:target_count]

    out: list[DdCandidateCompany] = []
    for row in picked:
        orgnr = str(row["organisationsnummer"])
        out.append(
            DdCandidateCompany(
                id=_candidate_id(orgnr),
                namn=str(row["namn"]),
                organisationsnummer=orgnr,
                alder_ar=int(row["alder_ar"]),
                omrade=str(row["omrade"]),
                resultat=row["resultat"],  # type: ignore[arg-type]
                omsattning_sek=int(row["omsattning_sek"]) if row.get("omsattning_sek") else None,
                anstallda=int(row["anstallda"]) if row.get("anstallda") else None,
                beskrivning=str(row.get("beskrivning") or ""),
            )
        )
    return out
