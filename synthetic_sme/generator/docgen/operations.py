from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import config
from ..model import Model
from ..util import fmt_sek, fmt_date_sv, rng
from .common import new_doc, heading, para, kv, table, right, save

ROOT = Path(__file__).resolve().parents[2]  # .../synthetic_sme
F = {n: ROOT / n for n in ("company", "management", "correspondence", "policies",
                           "projects", "employees", "customers", "suppliers")}

MANIFEST: list[dict] = []

ORG = "Nordviken Digital AB"
ORGNO = "559245-1673"
ADDR = "Kajplatsen 4, 115 27 Stockholm"

# ---------------------------------------------------------------------------
# hjälpfunktioner
# ---------------------------------------------------------------------------

def reg(doc_id: str, path: str, dtype: str, title: str, created: str,
        author_id: str, entities: list[str], **kw: Any) -> None:
    MANIFEST.append({
        "doc_id": doc_id,
        "path": path,
        "dtype": dtype,
        "title": title,
        "created": created,
        "author_id": author_id,
        "entities": entities,
        "version": kw.get("version", "1.0"),
        "valid_from": kw.get("valid_from"),
        "valid_to": kw.get("valid_to"),
        "event_ids": kw.get("event_ids", []),
        "supersedes": kw.get("supersedes"),
        "note": kw.get("note", ""),
    })


def csv_w(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        for r in rows:
            w.writerow([str(x).replace(";", ",") for x in r])


def eml_w(path: Path, thread: list[dict]) -> None:
    """Skriv en .eml-fil med en hel tråd (senaste meddelandet överst)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = []
    for i, msg in enumerate(thread):
        out.append(f"From: {msg['from_']}")
        out.append(f"To: {msg['to']}")
        if msg.get("cc"):
            out.append(f"Cc: {msg['cc']}")
        out.append(f"Date: {msg['date'].strftime('%a, %d %b %Y %H:%M:%S +0200')}")
        out.append(f"Subject: {msg['subject']}")
        out.append(f"Message-ID: <{msg.get('mid', path.stem + '-' + str(i))}@nordvikendigital.se>")
        out.append("MIME-Version: 1.0")
        out.append('Content-Type: text/plain; charset="utf-8"')
        out.append("")
        out.append(msg["body"])
        if i < len(thread) - 1:
            out.append("")
            out.append("=" * 72)
            out.append("  Ursprungligt meddelande")
            out.append("=" * 72)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso + "T09:00:00+02:00")


def head(doc, title: str, datum: str, author: str | None = None,
         doc_id: str | None = None, version: str | None = None) -> None:
    para(doc, f"{ORG}  ·  Org.nr {ORGNO}  ·  {ADDR}", italic=True)
    heading(doc, title, 0)
    kv(doc, "Datum", datum)
    if author:
        kv(doc, "Upprättad av", author)
    if version:
        kv(doc, "Version", version)
    if doc_id:
        kv(doc, "Dokument-ID", doc_id)
    para(doc, "")


def ksec(x: Any) -> str:
    """Tusentalskronor: 47100 -> '47 100 tkr'"""
    return fmt_sek(x)


def tkr(x: Any) -> str:
    return f"{int(round(float(x))):,}".replace(",", " ")


def table_rows(rows: list[list[Any]]) -> list[list[str]]:
    return [[str(c) for c in r] for r in rows]


# ---------------------------------------------------------------------------
# company/
# ---------------------------------------------------------------------------

def section_company(m: Model) -> None:
    fol = F["company"]

    # -- Bolagsordning -----------------------------------------------------
    d = new_doc()
    head(d, "Bolagsordning för Nordviken Digital AB", "Antagen 2018-03-12, senast ändrad 2023-06-01",
         "Bolagsverket", "DOC-COMP-001", "v4")
    para(d, "§ 1 Firma")
    para(d, "Bolagets firma är Nordviken Digital AB.")
    para(d, "§ 2 Säte")
    para(d, "Styrelsen ska ha sitt säte i Stockholms kommun.")
    para(d, "§ 3 Verksamhet")
    para(d, "Bolaget ska bedriva konsultverksamhet inom IT, systemutveckling och digitalisering samt därmed förenlig verksamhet.")
    para(d, "§ 4 Aktiekapital och antal aktier")
    para(d, "Aktiekapitalet ska utgöra lägst 250 000 kronor och högst 1 000 000 kronor. Antalet aktier ska vara lägst 2 500 och högst 10 000.")
    para(d, "§ 5 Styrelse")
    para(d, "Styrelsen ska bestå av lägst 3 och högst 5 ledamöter med högst 2 suppleanter.")
    para(d, "§ 6 Revisor")
    para(d, "Bolaget ska ha 1 revisor med 1 revisorssuppleant eller ett registrerat revisionsbolag.")
    para(d, "§ 7 Kallelse")
    para(d, "Kallelse till bolagsstämma ska ske genom brev med posten eller e-post till aktieägarna tidigast sex veckor och senast två veckor före stämman.")
    para(d, "§ 8 Räkenskapsår")
    para(d, "Bolagets räkenskapsår ska vara 1 oktober – 30 september.")
    para(d, "§ 9 Årsstämma")
    para(d, "På årsstämma ska följande ärenden förekomma: val av ordförande vid stämman, upprättande och godkännande av röstlängd, godkännande av dagordning, framläggande av årsredovisning och revisionsberättelse, beslut om fastställande av resultat- och balansräkning, beslut om dispositioner beträffande bolagets vinst eller förlust, beslut om ansvarsfrihet, fastställande av arvoden, val av styrelse och revisor, samt övriga ärenden som ankommer på stämman enligt aktiebolagslagen.")
    para(d, "§ 10 Firmateckning")
    para(d, "Firman tecknas av styrelsen samt av verkställande direktören var för sig.")
    save(d, fol / "bolagsordning.docx")
    reg("DOC-COMP-001", "company/bolagsordning.docx", "BOLAGSDOK",
        "Bolagsordning för Nordviken Digital AB", "2023-06-01", "P-038",
        ["ORG-NORDVIKEN"], version="4", note="Antagen 2018-03-12; senast ändrad 2023-06-01.")

    # -- Registreringsbevis --------------------------------------------------
    d = new_doc()
    head(d, "Registreringsbevis", "Utfärdat 2026-09-28", "Bolagsverket", "DOC-COMP-002")
    table(d, ["Uppgift", "Registrerat innehåll"], [
        ["Firma", "Nordviken Digital AB"],
        ["Organisationsnummer", "559245-1673"],
        ["Säte", "Stockholms kommun, Stockholms län"],
        ["Registreringsdatum", "2018-03-12"],
        ["Aktiekapital", "250 000 kr"],
        ["Antal aktier", "2 500"],
        ["Styrelse", "Eva Granlund, ordförande (invald 2018-03-12)"],
        ["Styrelse", "Per Lindström, ledamot (invald 2021-06-15)"],
        ["Styrelse", "Maja Lindqvist, ledamot (invald 2018-03-12)"],
        ["Verkställande direktör", "Maja Lindqvist"],
        ["Firmateckning", "Firman tecknas av styrelsen. Firman tecknas var för sig av verkställande direktören."],
        ["Revisor", "Revision & Tal AB, huvudansvarig Karin Åkesson"],
        ["Räkenskapsår", "1 oktober – 30 september"],
    ])
    para(d, "Registreringsbeviset har utfärdats på begäran av bolaget i samband med årsstämmoförberedelser.")
    save(d, fol / "registreringsbevis.docx")
    reg("DOC-COMP-002", "company/registreringsbevis.docx", "BOLAGSDOK",
        "Registreringsbevis Nordviken Digital AB", "2026-09-28", "SYSTEM",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "P-040"])

    # -- Aktiebok ------------------------------------------------------------
    d = new_doc()
    head(d, "Aktiebok", "Senast uppdaterad 2025-08-12", "Anders Bergström, CFO", "DOC-COMP-003")
    table(d, ["Aktieägare", "Personnr/Org.nr", "Antal aktier", "Andel"], [
        ["Maja Lindqvist", "19740512-XXXX", "1 500", "60,0 %"],
        ["Jonas Sandberg", "19790903-XXXX", "1 000", "40,0 %"],
    ])
    para(d, "Totalt antal aktier: 2 500 à 100 kr. Aktiekapital: 250 000 kr.")
    para(d, "Inga överlåtelser har registrerats sedan 2018-03-12.")
    save(d, fol / "aktiebok.docx")
    reg("DOC-COMP-003", "company/aktiebok.docx", "BOLAGSDOK",
        "Aktiebok", "2025-08-12", "P-003", ["ORG-NORDVIKEN", "P-001", "P-002"])

    # -- Ägardirektiv ---------------------------------------------------------
    d = new_doc()
    head(d, "Ägardirektiv för Nordviken Digital AB", "Beslutat 2021-10-05", "Eva Granlund, styrelseordförande", "DOC-COMP-004", "v2")
    para(d, "Ägarna (Maja Lindqvist 60 %, Jonas Sandberg 40 %) har fastställt följande direktiv för bolagets verksamhet:")
    para(d, "1. Lönsamhet: Avkastning på eget kapital ska över tid uppgå till minst 15 % per år.", bold=True)
    para(d, "2. Tillväxt: Omsättningen ska växa med minst 10 % per år utan att bruttomarginalen försämras.")
    para(d, "3. Soliditet: Soliditeten ska hållas över 25 % (bankens covenantkrav beaktas).")
    para(d, "4. Utdelning: Utdelning kan lämnas med högst 30 % av årets resultat efter skatt, under förutsättning att soliditets- och likviditetsmål uppfylls.")
    para(d, "5. Risk: Kundberoendet får inte överstiga 40 % av omsättningen för en enskild kund utan styrelsens godkännande.")
    para(d, "6. Hållbarhet och arbetsmiljö: Bolaget ska bedriva ett systematiskt arbetsmiljöarbete och följa tillämplig lagstiftning.")
    para(d, "Direktivet revideras vid behov, dock minst vart tredje år.")
    save(d, fol / "agardirektiv.docx")
    reg("DOC-COMP-004", "company/agardirektiv.docx", "BOLAGSDOK",
        "Ägardirektiv", "2021-10-05", "P-038", ["ORG-NORDVIKEN", "P-001", "P-002"],
        version="2", note="Beslutat av ägarna 2021-10-05.")

    # -- VD-instruktion -------------------------------------------------------
    d = new_doc()
    head(d, "VD-instruktion", "Reviderad 2025-09-25", "Eva Granlund, styrelseordförande", "DOC-COMP-005", "v3")
    para(d, "Styrelsen har den 25 september 2025 fastställt följande instruktion för verkställande direktören Maja Lindqvist.")
    para(d, "Beslutsgränser för VD (utan styrelsens godkännande)", bold=True)
    table(d, ["Ärendetyp", "Beloppsgräns"], [
        ["Tecknande av kund- eller leverantörsavtal", "Upp till 2 000 000 kr per avtal"],
        ["Investeringar (maskiner, inventarier, mjukvara)", "Upp till 500 000 kr per beslut"],
        ["Hyresavtal", "Upp till 3 års löptid"],
        ["Anställning och avskedande (ej VD)", "Ingen beloppsgräns, men befattningar i ledningsgruppen ska förankras med styrelseordföranden"],
        ["Låneupptagning", "VD får inte ta upp lån; checkräkningskredit hanteras inom ramen beslutad av styrelsen"],
    ])
    para(d, "Följande beslut kräver alltid styrelsens godkännande: avtal över 2 000 000 kr, investeringar över 500 000 kr, förvärv eller avyttring av rörelse, nyemission, teckningsoptionsprogram, längre avtal än 3 år samt förändring av firma eller säte.")
    para(d, "Rapportering")
    para(d, "VD ska månatligen, senast den 15:e i efterföljande månad, rapportera resultat, likviditet, beläggning och väsentliga risker till styrelsen. VD ska omedelbart informera styrelseordföranden om händelser av väsentlig betydelse.")
    para(d, "Firmateckning")
    para(d, "VD tecknar firman var för sig enligt bolagsordningen § 10.")
    save(d, fol / "vd-instruktion.docx")
    reg("DOC-COMP-005", "company/vd-instruktion.docx", "BOLAGSDOK",
        "VD-instruktion", "2025-09-25", "P-038", ["ORG-NORDVIKEN", "P-001"],
        version="3", event_ids=["EVT-031"],
        note="Reviderad i samband med styrelsemötet 2025-09-25. Beslutsgränser: avtal 2 MSEK, investeringar 500 kSEK.")

    # -- Attestordning --------------------------------------------------------
    d = new_doc()
    head(d, "Attestordning", "Reviderad 2025-06-01", "Anders Bergström, CFO", "DOC-COMP-006", "v3")
    table(d, ["Attestant", "Beloppsgräns (kr)", "Anmärkning"], [
        ["Maja Lindqvist, VD", "1 000 000", "Beslutsattest alla kostnadsslag"],
        ["Anders Bergström, CFO", "500 000", "Beslutsattest ekonomi och inköp"],
        ["Jonas Sandberg, CTO", "100 000", "IT- och SaaS-inköp"],
        ["Erik Norén, Leveranschef", "100 000", "Projektrelaterade inköp"],
        ["Petra Wahlgren, HR- och kontorschef", "50 000", "Kontors- och HR-relaterade inköp"],
    ])
    para(d, "Fakturor över 500 000 kr kräver två attester (beslutsattest + behörighetsattest).")
    para(d, "Abonnemang och SaaS-tjänster")
    para(d, "Löpande abonnemang upp till 10 000 kr per månad får tecknas av respektive systemägare, men ska attesteras av CFO innan första fakturan betalas. Abonnemang därutöver kräver beslut av CFO och VD gemensamt.")
    para(d, "Jäv")
    para(d, "Attest får inte utföras av den som har ekonomiskt intresse i transaktionen eller av den som själv är mottagare av ersättningen.")
    para(d, "Kontroll")
    para(d, "CFO genomför stickprovskontroll av attester kvartalsvis och rapporterar avvikelser till ledningsgruppen.")
    save(d, fol / "attestordning.docx")
    reg("DOC-COMP-006", "company/attestordning.docx", "BOLAGSDOK",
        "Attestordning", "2025-06-01", "P-003", ["ORG-NORDVIKEN", "P-001", "P-002", "P-004", "P-007"],
        version="3", note="SaaS-gräns 10 kkr/mån för systemägare; däröver CFO+VD.")

    # -- Organisationsschema --------------------------------------------------
    d = new_doc()
    head(d, "Organisationsschema", "Gäller fr.o.m. 2026-09-01", "Petra Wahlgren, HR- och kontorschef", "DOC-COMP-007", "v2")
    para(d, "Ledning (LED): Maja Lindqvist (VD), Jonas Sandberg (CTO), Anders Bergström (CFO)", bold=True)
    para(d, "Stab (STAB): Petra Wahlgren (HR/kontor), Sara Holm (Försäljning), Lisa Sundberg (Marknad), Erik Norén (Leveranschef)")
    para(d, "Leverans (LEV): Projektledare: David Ekström, Karin Olsson. Lösningsarkitekter: Tomas Berg, Nadia Haddad (fr.o.m. 2026-05-04). Utvecklare: Fredrik Lund, Emma Persson, Johan Wall, Oskar Nilsson, Camilla Westin, Viktor Lind, Elin Andersson, Alice Forsberg, Hugo Larsson. Test: Maria Gustavsson (testledare). UX: Johanna Sjöberg. Data/AI: Daniel Nyström. DevOps: Patrik Öberg, Simon Dahl. Support: VAKANT (Klara Månsson lämnade 2026-09-30).")
    para(d, "Underkonsulter: Kraftkod Konsult AB (2 utvecklare, SE-Billing t.o.m. 2026-07), Dataverket Nord AB (data engineer, GM-Bergdatasystem), Testhuset Stockholm AB (test, PF-Kundportal), Pixel & Form AB (UX, KF-Biljettsystem t.o.m. 2026-03).")
    para(d, "Antal anställda: 24 (per 2026-09-30), varav 22 tillsvidare.")
    save(d, fol / "organisationsschema.docx")
    reg("DOC-COMP-007", "company/organisationsschema.docx", "BOLAGSDOK",
        "Organisationsschema", "2026-09-01", "P-004", ["ORG-NORDVIKEN"] + [f"EMP-{i:03d}" for i in range(1, 32)],
        version="2", note="Supportansvarig vakant fr.o.m. 2026-10-01.")


# ---------------------------------------------------------------------------
# policies/
# ---------------------------------------------------------------------------

def section_policies(m: Model) -> None:
    fol = F["policies"]

    # -- DOC-POL-001 GDPR ----------------------------------------------------
    d = new_doc()
    head(d, "Personuppgiftspolicy (GDPR)", "Fastställd 2024-03-01", "Petra Wahlgren, HR- och kontorschef", "DOC-POL-001", "v3.0")
    para(d, "Syfte")
    para(d, "Policyn beskriver hur Nordviken Digital AB behandlar personuppgifter om kunder, leverantörer, medarbetare och kontakter i enlighet med dataskyddsförordningen (GDPR).")
    para(d, "Laglig grund per behandling", bold=True)
    table(d, ["Behandling", "Laglig grund"], [
        ["Kund- och avtalsadministration", "Avtal (art. 6.1 b)"],
        ["Fakturering och bokföring", "Rättslig förpliktelse (art. 6.1 c)"],
        ["Nyhetsbrev och marknadsutskick", "Samtycke (art. 6.1 a) eller berättigat intresse"],
        ["CRM-hantering av affärskontakter", "Berättigat intresse (art. 6.1 f)"],
        ["Rekrytering", "Berättigat intresse samt samtycke för lagring av ansökningar"],
        ["Anställningsadministration", "Avtal och rättslig förpliktelse"],
        ["Säkerhetsloggar och incidenthantering", "Rättslig förpliktelse / berättigat intresse"],
    ])
    para(d, "Gallringsfrister", bold=True)
    table(d, ["Uppgiftstyp", "Gallringsfrist"], [
        ["Bokföringsmaterial och fakturor", "7 år efter räkenskapsårets utgång"],
        ["Kunddokumentation och projektunderlag", "7 år efter avtalets upphörande"],
        ["Rekryteringsansökningar", "24 månader efter avslutad rekrytering"],
        ["CRM-kontakter utan avtal", "36 månader efter senaste kontakt"],
        ["Säkerhetskopior", "90 dagar"],
        ["Kameraövervakning (entré)", "30 dagar"],
    ])
    para(d, "Personuppgiftsbiträden")
    para(d, "Bolaget använder följande personuppgiftsbiträden: Pipeline AB (CRM, DPA 2022-12-01), Analytics Cloud Inc (analys, DPA + SCC 2025-05-01), Arkivet AB (dokument, DPA 2023-04-01), Cloudserve Ireland Ltd (M365/Azure, DPA 2024-01-01), Whiteboard AB (samarbetsyta, DPA SAKNAS – uppföljning pågår), Löneportalen AB (lön, DPA 2023-01-01), Personalen AB (HR, DPA 2023-06-01).")
    para(d, "Överföring till tredje land")
    para(d, "Analytics Cloud Inc (USA) används med standardavtalsklausuler (SCC). Känsliga personuppgifter får inte behandlas i tjänster utanför EU/EES. Se molntjänstpolicyn (DOC-POL-007).")
    para(d, "Incidenthantering")
    para(d, "Personuppgiftsincidenter ska anmälas internt till dataskyddssamordnaren (Petra Wahlgren) samma dag och till Integritetsskyddsmyndigheten inom 72 timmar om incidenten sannolikt medför risk.")
    para(d, "Roller")
    para(d, "Bolaget har inte utsett något dataskyddsombud (krav saknas). Dataskyddssamordnare är Petra Wahlgren.")
    save(d, fol / "personuppgiftspolicy_gdpr.docx")
    reg("DOC-POL-001", "policies/personuppgiftspolicy_gdpr.docx", "POLICY",
        "Personuppgiftspolicy (GDPR)", "2024-03-01", "P-004",
        ["ORG-NORDVIKEN", "SUP-009", "SUP-013", "SUP-003", "SUP-020", "SUP-015", "SUP-010", "SUP-022"],
        version="3.0", note="Whiteboard AB saknar DPA (uppföljning pågår).")

    # -- DOC-POL-002 IT-säkerhetspolicy ----------------------------------------
    d = new_doc()
    head(d, "IT-säkerhetspolicy", "Fastställd 2025-01-15", "Jonas Sandberg, CTO", "DOC-POL-002", "v2.1")
    para(d, "1. Åtkomst och identitet: Alla system ska använda multifaktorautentisering (MFA). Lösenord ska vara minst 14 tecken och bytas vid misstanke om kompromettering.")
    para(d, "2. Behörigheter: Behörigheter ska följa principen om minsta möjliga behörighet enligt behörighetspolicyn (DOC-POL-008). Genomgång av behörigheter sker kvartalsvis.")
    para(d, "3. Enheter: Företagets bärbara datorer ska vara krypterade och hanterade via central MDM. Privata enheter får inte användas för kunddata.")
    para(d, "4. Nätverk: Fjärranslutning sker via VPN (Säkra Nät AB). Öppna nätverk kräver VPN.")
    para(d, "5. Molntjänster: Endast molntjänster godkända enligt molntjänstpolicyn (DOC-POL-007) får användas för bolagsdata.")
    para(d, "6. Säkerhetskopiering: Backup tas dagligen (Säkerhetskopian AB). Återläsningstest sker halvårsvis.")
    para(d, "7. Incidenthantering: Säkerhetsincidenter ska rapporteras till CTO samma dag och dokumenteras i säkerhetsincidentloggen.")
    para(d, "8. Avslutad anställning: Åtkomst ska stängas senast 24 timmar efter sista arbetsdag.")
    para(d, "9. Utbildning: Alla medarbetare genomgår säkerhetsutbildning vid anställning och därefter årligen.")
    save(d, fol / "it_sakerhetspolicy.docx")
    reg("DOC-POL-002", "policies/it_sakerhetspolicy.docx", "POLICY",
        "IT-säkerhetspolicy", "2025-01-15", "P-002", ["ORG-NORDVIKEN", "SUP-008", "SUP-021"],
        version="2.1")

    # -- DOC-POL-003 Sekretesspolicy ------------------------------------------
    d = new_doc()
    head(d, "Sekretesspolicy", "Fastställd 2024-06-01 (mall från 2023-02-15)", "Petra Wahlgren, HR- och kontorschef", "DOC-POL-003", "v2.0")
    para(d, "1. Omfattning: Policyn gäller alla medarbetare, inhyrd personal och styrelseledamöter och omfattar all information om kunder, leverantörer, priser, kalkyler, affärsstrategier och interna system.")
    para(d, "2. Sekretess: Uppgifter som rör kunders verksamhet får inte röjas för obehöriga. Särskilda sekretessåtaganden i kundavtal (NDA) har företräde framför denna policy.")
    para(d, "3. Tystnadsplikt efter anställningens slut: Sekretessen gäller även efter att anställningen upphört.")
    para(d, "4. Sociala medier: Bolagsinformation får inte diskuteras i sociala medier utan VD:s godkännande.")
    para(d, "5. Konkurrensklausuler: Eventuella konkurrensklausuler i anställningsavtal hanteras enligt kollektivavtal och tillämplig praxis. Se särskilda rutiner för nyckelpersoner.")
    para(d, "6. Rapportering: Misstankar om brott mot sekretessen rapporteras till närmaste chef eller VD.")
    save(d, fol / "sekretesspolicy.docx")
    reg("DOC-POL-003", "policies/sekretesspolicy.docx", "POLICY",
        "Sekretesspolicy", "2024-06-01", "P-004", ["ORG-NORDVIKEN"],
        version="2.0", note="Baserad på mall från 2023-02-15.")

    # -- DOC-POL-004 AI-policy ------------------------------------------------
    d = new_doc()
    head(d, "AI-policy", "Beslutad av ledningsgruppen 2026-01-30, gäller fr.o.m. 2026-02-01", "Jonas Sandberg, CTO", "DOC-POL-004", "v1.0")
    para(d, "Syfte")
    para(d, "Policyn anger hur generativa AI-verktyg får användas i Nordviken Digital AB, i linje med beslutet om det interna AI-initiativet (ND-Intern AI, budget 1,2 MSEK 2026).")
    para(d, "Tillåtna verktyg", bold=True)
    para(d, "Godkända verktyg: Modellfabriken AB (API-access) och Analytics Cloud Inc (analys). Användning av öppna konsumenttjänster (t.ex. publika chattmodeller) med bolags- eller kunddata är förbjuden.")
    para(d, "Krav vid användning", bold=True)
    table(d, ["Krav", "Beskrivning"], [
        ["Källhänvisning", "Alla AI-genererade svar som används i kundleveranser eller interna beslut ska ha verifierbar källhänvisning."],
        ["Mänsklig granskning", "AI-genererat material ska alltid granskas av en ansvarig medarbetare före användning."],
        ["Ingen känslig data", "Känsliga personuppgifter och kundspecifika produktionsdata får inte skickas till AI-modeller utan särskilt godkännande."],
        ["Loggning", "AI-användning ska loggas (verktyg, syfte, promptkategori)."],
        ["Utbildning", "Medarbetare som använder AI-verktyg ska ha genomgått introduktion (utbildningsplan 2026)."],
    ])
    para(d, "Ansvarsfördelning")
    para(d, "Daniel Nyström (Data/AI-specialist) är samordnare för AI-initiativet och ansvarar för utvärdering av verktyg och uppföljning av policyn. Systemägare ansvarar för att verktyg de beställer är godkända.")
    para(d, "Uppföljning")
    para(d, "Policyn följs upp i samband med ledningsgruppens kvartalsgenomgångar. Incidenter rapporteras som säkerhetsincidenter.")
    save(d, fol / "ai_policy.docx")
    reg("DOC-POL-004", "policies/ai_policy.docx", "POLICY",
        "AI-policy", "2026-01-30", "P-002",
        ["ORG-NORDVIKEN", "P-026", "SUP-012", "SUP-013", "PRJ-091"],
        valid_from="2026-02-01", event_ids=["EVT-044"],
        note="Beslutad av ledningsgruppen 2026-01-30 (DOC-MGMT-008).")

    # -- DOC-POL-005 Resepolicy ------------------------------------------------
    d = new_doc()
    head(d, "Resepolicy", "Fastställd 2022-04-01", "Petra Wahlgren, HR- och kontorschef", "DOC-POL-005", "v1.1")
    table(d, ["Område", "Regel"], [
        ["Tåg vs flyg", "Tåg ska väljas för resor under 5 timmar; flyg endast vid längre sträckor eller när tåg saknas."],
        ["Hotell", "Högst 1 800 kr per natt inkl. moms utan särskilt godkännande."],
        ["Hyrbil", "Mellanklass eller mindre; större fordon kräver godkännande."],
        ["Traktamente", "Enligt Skatteverkets schabloner; utbetalas via lönesystemet."],
        ["Milersättning", "25 kr/mil vid tjänstekörning med egen bil (enligt Skatteverket)."],
        ["Bokning", "Alla resor bokas via Resebolaget Nord AB."],
        ["Godkännande", "Resor över 15 000 kr kräver förhandsgodkännande av närmaste chef."],
    ])
    save(d, fol / "resepolicy.docx")
    reg("DOC-POL-005", "policies/resepolicy.docx", "POLICY",
        "Resepolicy", "2022-04-01", "P-004", ["ORG-NORDVIKEN", "SUP-028"], version="1.1")

    # -- DOC-POL-006 Arbetsmiljöpolicy -----------------------------------------
    d = new_doc()
    head(d, "Arbetsmiljöpolicy", "Fastställd 2021-09-01, reviderad 2026-02-10", "Petra Wahlgren, HR- och kontorschef", "DOC-POL-006", "v2.0")
    para(d, "Nordviken Digital AB ska ha en god arbetsmiljö där ingen skadas av arbetet. Arbetsmiljöarbetet bedrivs systematiskt (SAM) med årliga riskbedömningar och skyddsronder.")
    para(d, "Fokusområden:")
    para(d, "– Psykosocial arbetsmiljö: arbetsbelastning, återhämtning och tydliga förväntningar. Övertid ska följas upp månadsvis.")
    para(d, "– Fysisk arbetsmiljö: arbetsplatser, skärmarbete och ergonomi.")
    para(d, "– Rehabilitering: tidig kontakt och anpassning vid sjukfrånvaro.")
    para(d, "– Alkohol och droger: nolltolerans under arbetstid.")
    para(d, "Ansvar: VD har det övergripande ansvaret. Petra Wahlgren samordnar arbetsmiljöarbetet. Medarbetare ansvarar för att rapportera risker och tillbud.")
    save(d, fol / "arbetsmiljopolicy.docx")
    reg("DOC-POL-006", "policies/arbetsmiljopolicy.docx", "POLICY",
        "Arbetsmiljöpolicy", "2026-02-10", "P-004", ["ORG-NORDVIKEN"],
        version="2.0", note="Reviderad i samband med SAM-riskbedömningen 2026-02-10.")

    # -- DOC-POL-007 Molntjänstpolicy ------------------------------------------
    d = new_doc()
    head(d, "Molntjänstpolicy", "Fastställd 2025-12-01", "Jonas Sandberg, CTO", "DOC-POL-007", "v1.2")
    para(d, "1. Godkända tjänster: Endast molntjänster i systemförteckningen får användas för bolagsdata. Ny SaaS-tjänst kräver säkerhetsbedömning (se leverantörsbedömningar) och godkännande av CTO och CFO.")
    para(d, "2. Tredjelandsöverföring: Analytics Cloud Inc (SUP-013, USA) används med standardavtalsklausuler (SCC, tecknade 2025-05-01). Känsliga personuppgifter får inte behandlas i tjänster utanför EU/EES. Övriga tjänster ska hålla data inom EU/EES.")
    para(d, "3. Omvänd skattskyldighet: För tjänster från leverantörer utanför Sverige (t.ex. Cloudserve Ireland Ltd) tillämpas omvänd skattskyldighet enligt mervärdesskattelagen.")
    para(d, "4. Personuppgiftsbiträdesavtal (DPA) ska finnas med samtliga biträden före användning.")
    para(d, "5. Data: Kundproduktionsdata får endast ligga i tjänster godkända för den dataklassen. Säkerhetskopiering enligt IT-säkerhetspolicyn.")
    para(d, "6. Exit: För kritiska tjänster ska exportmöjlighet och reservrutin finnas dokumenterad (se reservrutinsförteckning).")
    save(d, fol / "molntjanstpolicy.docx")
    reg("DOC-POL-007", "policies/molntjanstpolicy.docx", "POLICY",
        "Molntjänstpolicy", "2025-12-01", "P-002",
        ["ORG-NORDVIKEN", "SUP-013", "SUP-003"], version="1.2",
        note="SCC för SUP-013 tecknade 2025-05-01; känsliga uppgifter ej tillåtna i USA-tjänster.")

    # -- DOC-POL-008 Behörighetspolicy -----------------------------------------
    d = new_doc()
    head(d, "Behörighetspolicy", "Fastställd 2024-10-01", "Jonas Sandberg, CTO", "DOC-POL-008", "v1.1")
    para(d, "1. Princip: Behörigheter tilldelas enligt principen om minsta möjliga behörighet och endast efter behov i tjänsten.")
    para(d, "2. Administratörskonton: Administratörsrättigheter ska ligga på separata konton och användas sparsamt. Antalet administratörer per system ska hållas så lågt som möjligt.")
    para(d, "3. Genomgång: Systemägare går igenom behörigheter kvartalsvis och rapporterar avvikelser till CTO (se behörighetsmatris).")
    para(d, "4. Avslut: Vid avslutad anställning stängs åtkomst inom 24 timmar. Vid rollbyte omprövas behörigheterna.")
    para(d, "5. Kundmiljöer: Åtkomst till kundmiljöer styrs av respektive kundavtal och godkänns av leveranschef.")
    save(d, fol / "behorighetspolicy.docx")
    reg("DOC-POL-008", "policies/behorighetspolicy.docx", "POLICY",
        "Behörighetspolicy", "2024-10-01", "P-002", ["ORG-NORDVIKEN"], version="1.1")


def _board_head(d, datum, nr, place="Bolagets kontor, Kajplatsen 4, Stockholm"):
    para(d, f"{ORG}  ·  Org.nr {ORGNO}")
    heading(d, f"Styrelseprotokoll nr {nr}", 0)
    kv(d, "Sammanträdesdatum", datum)
    kv(d, "Plats", place)
    para(d, "")


def _attendance(d, rows):
    kv(d, "Närvarande", ", ".join(rows))
    para(d, "")


def section_management(m: Model) -> None:
    fol = F["management"]

    # =====================================================================
    # STYRELSEPROTOKOLL
    # =====================================================================
    # -- DOC-BOARD-001 (2024-11-21) ----------------------------------------
    d = new_doc()
    _board_head(d, "21 november 2024", "1/2024")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Jonas Sandberg (adjungerad)", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden hälsade välkommen och förklarade mötet öppnat. Dagordningen godkändes.")
    para(d, "§ 2 FY25-budget (2024-10-01 – 2025-09-30)")
    para(d, "CFO presenterade budgetförslaget för FY25: nettoomsättning 41 000 000 kr, EBIT-mål 6,0 %. Styrelsen diskuterade beläggningsantagandet (82 %) och rekryteringsplanen.")
    para(d, "Beslut: Styrelsen fastställde FY25-budgeten med följande ramar: (a) nettoomsättning 41 MSEK och EBIT-mål 6 %, (b) bibehållen investeringsnivå, (c) rekryteringsplan om 6 nyanställningar under året, (d) målsatt beläggningsgrad lägst 82 %.")
    para(d, "§ 3 Investeringar")
    para(d, "VD föredrog inköp av 20 laptops samt skärmar för 350 000 kr exkl. moms från Datorlagret AB. Beslut: Inköpet godkänns och ska aktiveras som datorer med 3 års avskrivning.")
    para(d, "§ 4 Kundläget")
    para(d, "SE-Billing-projektet (Skogsbygdens Energi) löper enligt plan. Norrhamns Hamn har framfört synpunkter på prestanda i NH-Logistikportalen; leveranschefen återrapporterar åtgärdsplan vid nästa möte.")
    para(d, "§ 5 Övriga frågor")
    para(d, "Konkurrensklausulen i Gustav Petterssons anställningsavtal (avgång 2024-11-15 till Blå Ocean IT AB) diskuterades. Beslut: VD inhämtar rättslig bedömning från Advokatfirman Krav & Klar.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 12.15.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2024-11-21.docx")
    reg("DOC-BOARD-001", "management/styrelseprotokoll_2024-11-21.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 1/2024", "2024-11-21", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "P-002", "P-032"],
        event_ids=["EVT-005"])

    # -- DOC-BOARD-002 (2025-02-10) ----------------------------------------
    d = new_doc()
    _board_head(d, "10 februari 2025", "2/2025")
    _attendance(d, ["Eva Granlund (ordförande)", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat. Per Lindström var frånvarande (anmält förhinder).")
    para(d, "§ 2 Kvartalsrapport Q1 (oktober–december 2024)")
    para(d, "CFO presenterade kvartalsrapporten. Nettoomsättningen uppgick till 6,5 MSEK och rörelseresultatet var svagt negativt. Styrelsen noterade att checkräkningskrediten varit utnyttjad till 190 000 kr i december och att likviditeten försämras.")
    para(d, "Beslut: Styrelsen uppdrar åt CFO att upprätta månatlig likviditetsprognos och rapportera avvikelser över 500 000 kr omedelbart.")
    para(d, "§ 3 Likviditet och bankrelation")
    para(d, "VD informerade om planerat bankmöte med Norrvidden Bank under våren. Styrelsen betonade vikten av att säkra förnyad checkkredit.")
    para(d, "§ 4 Övriga frågor")
    para(d, "ÖH-Webbplattformen (Örby Handel & Logistik) – kunden har framfört acceptansanmärkningar mot slutfakturan. Ärendet följs löpande.")
    para(d, "§ 5 Mötets avslutande")
    para(d, "Mötet avslutades kl. 15.40.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2025-02-10.docx")
    reg("DOC-BOARD-002", "management/styrelseprotokoll_2025-02-10.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 2/2025", "2025-02-10", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-001"], event_ids=["EVT-013"])

    # -- DOC-BOARD-003 (2025-05-19) ----------------------------------------
    d = new_doc()
    _board_head(d, "19 maj 2025", "3/2025")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat och dagordningen godkändes.")
    para(d, "§ 2 Kvartalsrapport Q2 (januari–mars 2025)")
    para(d, "CFO presenterade kvartalsrapporten. Nettoomsättningen uppgick till 10,3 MSEK med förbättrat resultat. Checkräkningskrediten utnyttjades som mest med 1 180 000 kr i mars. Styrelsen godkände rapporten.")
    para(d, "§ 3 Kundkoncentration")
    para(d, "Skogsbygdens Energi AB (SEAB) svarade för 30 % av omsättningen under kvartalet. Styrelsen diskuterade beroendet och beslutade att ledningen vid varje styrelsemöte ska redovisa SEAB:s andel samt pågående spridningsåtgärder.")
    para(d, "§ 4 Teckningsoptionsprogram")
    para(d, "Beslut: Styrelsen beslutar att inrätta ett teckningsoptionsprogram motsvarande 3 % av aktierna för nyckelpersoner (Maja Lindqvist, Jonas Sandberg, Anders Bergström). Villkor och tilldelning fastställs av styrelsen senare under året; värdering utförs enligt Black & Scholes.")
    para(d, "§ 5 Rekrytering")
    para(d, "Leveranschefen flaggade kapacitetsbrist i maj–juni (beläggning över 95 %). Styrelsen beslutade att prioritera rekrytering av DevOps och utvecklare samt öka användningen av underkonsulter.")
    para(d, "§ 6 Beslutsuppföljning")
    table(d, ["Beslut", "Status"], [
        ["Månatlig likviditetsprognos (2025-02-10)", "Genomfört"],
        ["Rättslig bedömning konkurrensklausul Gustav Pettersson", "Pågående"],
        ["Utvärdering av CRM-alternativ (från 2024-11-21)", "Ej påbörjad"],
    ])
    para(d, "§ 7 Mötets avslutande")
    para(d, "Mötet avslutades kl. 16.05.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2025-05-19.docx")
    reg("DOC-BOARD-003", "management/styrelseprotokoll_2025-05-19.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 3/2025", "2025-05-19", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001"], event_ids=["EVT-022", "EVT-024"],
        note="Innehåller beslut om teckningsoptionsprogram (3 %).")

    # -- DOC-BOARD-004 (2025-09-25) ----------------------------------------
    d = new_doc()
    _board_head(d, "25 september 2025", "4/2025")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Jonas Sandberg (adjungerad)", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Bankmötet 2025-09-15")
    para(d, "VD och CFO redogjorde för bankmötet med Norrvidden Bank (se DOC-BANK-001). Banken ställer krav på kvartalsvisa covenantrapporter (soliditet ≥ 25 %, EBITDA > 0) samt månatlig likviditetsprognos som villkor för förnyad checkkredit. Styrelsen beslutade att införa rapporteringen med omedelbar verkan.")
    para(d, "§ 3 FY26-budget (2025-10-01 – 2026-09-30)")
    para(d, "CFO presenterade budgetförslaget: nettoomsättning 47 000 000 kr, EBIT-mål 7,0 % (3 290 000 kr). Budgeten bygger på SE-Integration med 550–600 debiterbara timmar per månad, fortsatt samarbete med Mossbackens Mekaniska hela året samt två planerade rekryteringar.")
    para(d, "Beslut: Styrelsen fastställde FY26-budgeten (bilaga, DOC-BUDG-001) och investeringsramen för produktutveckling om 2 400 000 kr (ND-Intern plattform).")
    para(d, "§ 4 VD-instruktion")
    para(d, "Beslut: Styrelsen fastställde reviderad VD-instruktion (DOC-COMP-005) med beslutsgränser: avtal upp till 2 000 000 kr, investeringar upp till 500 000 kr.")
    para(d, "§ 5 Övriga frågor")
    para(d, "Förlikningen med Tobias Lindqvist (avgångsvederlag 3 månadslöner, 141 000 kr) noterades som avslutad.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 14.50.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2025-09-25.docx")
    reg("DOC-BOARD-004", "management/styrelseprotokoll_2025-09-25.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 4/2025", "2025-09-25", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "P-002", "PRJ-090"],
        event_ids=["EVT-031"], note="Fastställer FY26-budget (47 MSEK, EBIT 7 %) och investeringsram 2,4 MSEK.")

    # -- DOC-BOARD-005 (2025-11-24) ----------------------------------------
    d = new_doc()
    _board_head(d, "24 november 2025", "5/2025")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Bokslut FY2025")
    para(d, "CFO presenterade bokslutskommunikén för FY2025 (DOC-FIN-001): nettoomsättning 42 638 187 kr, resultat efter skatt −264 298 kr. Rörelseresultatet uppgick till −209 936 kr. Revisionen (Revision & Tal AB, arvode 95 000 kr) har inte föranlett några väsentliga anmärkningar.")
    para(d, "Beslut: Styrelsen godkände bokslutskommunikén för publicering.")
    para(d, "§ 3 Disposition av resultatet")
    para(d, "Med hänsyn till det negativa resultatet och likviditetsläget föreslås ingen utdelning. Styrelsen beslutade att skjuta upp utdelningsfrågan till årsstämman.")
    para(d, "§ 4 Kundläget")
    para(d, "SEAB:s andel av omsättningen var 27,8 % under FY25. Försäljningschefen redovisade pågående dialoger med Gråvikens kommun och Polstjärnan Försäkring.")
    para(d, "§ 5 Övriga frågor")
    para(d, "Inga övriga frågor förelåg utöver vad som anmälts.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 15.30.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2025-11-24.docx")
    reg("DOC-BOARD-005", "management/styrelseprotokoll_2025-11-24.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 5/2025", "2025-11-24", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001"], event_ids=["EVT-038"],
        note="Godkänner bokslutskommuniké FY25; utdelning skjuts till årsstämman.")

    # -- DOC-BOARD-006 (2026-03-12) ----------------------------------------
    d = new_doc()
    _board_head(d, "12 mars 2026", "6/2026")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Delårsrapport för perioden oktober–december 2025")
    para(d, "CFO presenterade delårsrapporten: nettoomsättning 15,1 MSEK, vilket överstiger budget med 4,7 MSEK. Överprestationen förklaras av högre SEAB-volymer (SE-Integration) än budgeterat. SEAB:s andel av omsättningen uppgick till 35 %.")
    para(d, "Styrelsen uttryckte oro för SEAB-beroendet och beslutade om en fördjupad scenarioanalys av effekterna om SEAB skulle minska eller avsluta samarbetet. Analysen ska redovisas vid nästa styrelsemöte.")
    para(d, "§ 3 Likviditet och bank")
    para(d, "CFO informerade om att banken bekräftar förnyad checkkredit till 2026-12-31 under förutsättning av covenantrapportering (möte 2026-03-20).")
    para(d, "§ 4 Tilläggshyra kontorsplan")
    para(d, "VD informerade om beslutad tilläggshyra av extra våningsplan fr.o.m. 2026-07-01 (48 000 kr/mån) för planerad tillväxt.")
    para(d, "§ 5 Personal")
    para(d, "HR-chefen redovisade att Magnus Ryd sagt upp sig (sista dag 2026-03-31). Rekrytering av ersättare pågår.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 14.20.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2026-03-12.docx")
    reg("DOC-BOARD-006", "management/styrelseprotokoll_2026-03-12.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 6/2026", "2026-03-12", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "CUS-001"],
        event_ids=["EVT-051"])

    # -- DOC-BOARD-007 utkast v0.9 (2026-05-25) ------------------------------
    d = new_doc()
    _board_head(d, "25 maj 2026", "7/2026")
    kv(d, "Version", "Utkast v0.9 – ej undertecknat")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Kvartalsrapport Q3 (januari–mars 2026)")
    para(d, "CFO presenterade kvartalsrapporten: nettoomsättning 15,8 MSEK. Resultatet förbättrades jämfört med föregående kvartal.")
    para(d, "§ 3 Projektstatus")
    table(d, ["Projekt", "Status"], [
        ["SE-Billing", "Slutlevererad"],
        ["TS-Produktionsportal", "Försenad – viteförhandling pågår"],
        ["SU-Produktionssystem", "Pågående enligt plan"],
        ["GV-Digitalisering", "Pågående"],
        ["LM-Lärplattform", "Pågående, slutleverans planerad 2026-08"],
    ])
    para(d, "§ 4 Åtgärder mot förseningar och underfakturering")
    para(d, "Styrelsen efterfrågade åtgärder mot försenade projekt och den upptäckta underfaktureringen (KF-Biljettsystem). Leveranschefen ska presentera en åtgärdsplan inom tre veckor.")
    para(d, "§ 5 Prognos")
    para(d, "Styrelsen beslutade att CFO reviderar helårsprognosen och presenterar bas-, worst- och best-scenarier senast 2026-06-01.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 15.10.")
    right(d, "Utkast – väntar på justeringar")
    save(d, fol / "styrelseprotokoll_2026-05-25_utkast_v0.9.docx")
    reg("DOC-BOARD-007U", "management/styrelseprotokoll_2026-05-25_utkast_v0.9.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 7/2026 (utkast v0.9)", "2026-05-25", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "PRJ-001"],
        version="0.9", event_ids=["EVT-058"],
        note="Utkast till DOC-BOARD-007. I utkastet anges SE-Billing som 'Slutlevererad'; i den slutliga versionen (v1.0) ändrat till 'Pågående'.")

    # -- DOC-BOARD-007 slutlig v1.0 (2026-05-25) ------------------------------
    d = new_doc()
    _board_head(d, "25 maj 2026", "7/2026")
    kv(d, "Version", "v1.0 – justerat och undertecknat")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Kvartalsrapport Q3 (januari–mars 2026)")
    para(d, "CFO presenterade kvartalsrapporten: nettoomsättning 15,8 MSEK. Resultatet förbättrades jämfört med föregående kvartal.")
    para(d, "§ 3 Projektstatus")
    table(d, ["Projekt", "Status"], [
        ["SE-Billing", "Pågående – slutleverans planerad 2026-07-15"],
        ["TS-Produktionsportal", "Försenad – viteförhandling pågår"],
        ["SU-Produktionssystem", "Pågående enligt plan"],
        ["GV-Digitalisering", "Pågående"],
        ["LM-Lärplattform", "Pågående, slutleverans planerad 2026-08"],
    ])
    para(d, "§ 4 Åtgärder mot förseningar och underfakturering")
    para(d, "Styrelsen efterfrågade åtgärder mot försenade projekt och den upptäckta underfaktureringen (KF-Biljettsystem). Leveranschefen ska presentera en åtgärdsplan inom tre veckor.")
    para(d, "§ 5 Prognos")
    para(d, "Styrelsen beslutade att CFO reviderar helårsprognosen och presenterar bas-, worst- och best-scenarier senast 2026-06-01.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 15.10.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2026-05-25.docx")
    reg("DOC-BOARD-007", "management/styrelseprotokoll_2026-05-25.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 7/2026", "2026-05-25", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "PRJ-001"],
        version="1.0", event_ids=["EVT-058"], supersedes="DOC-BOARD-007U",
        note="Slutlig version; SE-Billing anges som 'Pågående' (slutleverans 2026-07-15).")

    # -- DOC-BOARD-008 (2026-09-28) ------------------------------------------
    d = new_doc()
    _board_head(d, "28 september 2026", "8/2026")
    _attendance(d, ["Eva Granlund (ordförande)", "Per Lindström", "Maja Lindqvist", "Jonas Sandberg (adjungerad)", "Anders Bergström (protokollförare)"])
    para(d, "§ 1 Mötets öppnande")
    para(d, "Ordföranden förklarade mötet öppnat.")
    para(d, "§ 2 Preliminärt bokslut FY2026")
    para(d, "CFO presenterade preliminära siffror för FY2026: nettoomsättning cirka 54,3 MSEK, resultat efter skatt cirka 6,3 MSEK. SEAB:s andel av omsättningen uppgick till 34,4 %. Slutlig årsredovisning föreläggs styrelsen i november.")
    para(d, "§ 3 Utdelningsfrågan")
    para(d, "Diskussion fördes om utdelning. Styrelsen beslutade att bordlägga utdelningsfrågan till årsstämman, där styrelsens förslag presenteras tillsammans med likviditets- och investeringsbehov för FY27.")
    para(d, "§ 4 Riskrapportering")
    para(d, "Styrelsen konstaterade att riskregistret (DOC-RISK-001) inte har uppdaterats sedan maj och att flera risker saknar ägare. Beslut: Till nästa styrelsemöte (2026-11-26) ska en riskrapport presenteras där varje risk har ägare, åtgärd OCH källhänvisning till underliggande dokument.")
    para(d, "§ 5 Personal")
    para(d, "HR-chefen informerade om att supportansvarig (Klara Månsson) lämnat bolaget 2026-09-30 och att rollen är vakant. Rekryteringsläget och belastningen på supporten diskuterades.")
    para(d, "§ 6 Mötets avslutande")
    para(d, "Mötet avslutades kl. 15.45.")
    right(d, "Eva Granlund, ordförande")
    right(d, "Anders Bergström, protokollförare")
    save(d, fol / "styrelseprotokoll_2026-09-28.docx")
    reg("DOC-BOARD-008", "management/styrelseprotokoll_2026-09-28.docx", "PROTOKOLL",
        "Styrelseprotokoll nr 8/2026", "2026-09-28", "P-003",
        ["ORG-NORDVIKEN", "P-038", "P-039", "P-001", "P-002", "CUS-001"],
        event_ids=["EVT-069"], note="Utdelning bordlagd till årsstämman; riskrapport med källhänvisningar krävs till nästa möte.")

    # =====================================================================
    # LEDNINGSGRUPPSPROTOKOLL DOC-MGMT-001..010
    # =====================================================================
    def mgmt(datum, title, items, doc_id, evt, note=""):
        d = new_doc()
        para(d, f"{ORG}  ·  Intern handling")
        heading(d, f"Ledningsgruppsprotokoll {title}", 0)
        kv(d, "Datum", datum)
        kv(d, "Närvarande", "Maja Lindqvist (VD, ordförande), Jonas Sandberg (CTO), Anders Bergström (CFO), Petra Wahlgren (HR), Sara Holm (Försäljning), Erik Norén (Leverans)")
        kv(d, "Protokollförare", "Petra Wahlgren")
        kv(d, "Dokument-ID", doc_id)
        para(d, "")
        for i, (rub, txt) in enumerate(items, 1):
            para(d, f"{i}. {rub}", bold=True)
            for line in txt:
                para(d, line)
            para(d, "")
        save(d, fol / f"ledningsgruppsprotokoll_{datum.replace('-', '_')}.docx")
        reg(doc_id, f"management/ledningsgruppsprotokoll_{datum.replace('-', '_')}.docx",
            "PROTOKOLL", f"Ledningsgruppsprotokoll – {title}", datum, "P-004",
            ["ORG-NORDVIKEN", "P-001", "P-002", "P-003", "P-004", "P-005", "P-007"],
            event_ids=evt, note=note)

    mgmt("2024-10-07", "Budgetförutsättningar FY25", [
        ("Budgetförutsättningar FY25", [
            "Anders gick igenom budgetförutsättningarna för FY25 (okt 2024–sep 2025): omsättningsmål 41 MSEK, EBIT-mål 6 %, beläggning 82 %.",
            "Sara redovisade pipelinen: SEAB-förvaltning, KL-Vårdportal och KF-Biljettsystem är de största posterna.",
            "Beslut: Underlaget skickas till styrelsen inför styrelsemötet 2024-11-21."]),
        ("Risker", ["Anders lyfte likviditetsrisken vid försenade kundbetalningar; rutin för påminnelser ses över."]),
        ("Övrigt", ["Nästa möte: 2024-11-04."]),
    ], "DOC-MGMT-001", ["EVT-001"])

    mgmt("2024-12-20", "Halvårsvis riskgenomgång", [
        ("Riskgenomgång", [
            "Anders presenterade uppdaterat riskregister (DOC-RISK-001 v1.0). Topprisker: kundkoncentration SEAB, nyckelpersonsberoende (Daniel Nyström data/AI, Tomas Berg arkitektur), avtalsrisk ÖH (obegränsat ansvar).",
            "Beslut: Riskregistret skickas till styrelsen; nyckelpersonsrisken och SEAB-beroendet lyfts till nästa styrelsemöte."]),
        ("NH-Logistikportal", [
            "Norrhamns Hamn har klagat på prestanda för tredje gången (se DOC-COM-001). Erik ansvarar för åtgärdsplan: prestandatest + hotfix senast 2025-01-31."]),
        ("Övrigt", ["Klagomålshantering: alla kundklagomål ska loggas i klagomålsregistret."]),
    ], "DOC-MGMT-002", ["EVT-008"], note="Uppdaterar DOC-RISK-001.")

    mgmt("2025-01-07", "Uppstart SE-Integration", [
        ("SE-Integration (SEAB)", [
            "Uppstart av SE-Integration – löpande konsultstöd till Skogsbygdens Energi, 1 150 kr/h initialt (inom ramavtal CTR-2023-002).",
            "Bemanning: Rasmus Holm och Fredrik Lund initialt, Erik Norén ansvarar för leveransen."]),
        ("Rekrytering", ["DevOps-rekrytering pågår (Patrik Öberg började 2024-11-01); ytterligare en utvecklare planeras i mars."]),
    ], "DOC-MGMT-003", ["EVT-009"])

    mgmt("2025-04-28", "Kapacitetsbrist i leverans", [
        ("Kapacitet", [
            "Erik flaggade kapacitetsbrist i leveransteamet: beläggningen överstiger 95 % i maj–juni.",
            "Beslut: (a) öka användningen av underkonsulter (Kraftkod Konsult AB för SE-Billing), (b) prioritera rekrytering av utvecklare och DevOps."]),
        ("SE-Billing", ["Projektet har halkat efter med cirka 6 veckor. David tar fram en återhämtningsplan till nästa möte."]),
        ("Övrigt", ["Lönerevisionen 2025 är klar: 8 medarbetare fick höjningar fr.o.m. 2025-04-01."]),
    ], "DOC-MGMT-004", ["EVT-021"])

    mgmt("2025-08-31", "Likviditet inför bankmöte", [
        ("Likviditetsläget", [
            "Likviditeten var som mest ansträngd i mars (checkkrediten utnyttjad till 1 180 000 kr). Läget har förbättrats.",
            "Beslut: Veckovisa likviditetsavstämningar införs inför bankmötet 2025-09-15. Anders sammanställer underlaget (covenants, prognos)."]),
        ("Försäljning", ["Sara: Polstjärnan Försäkring (PF-Kundportal) går bra; dialog om utökning pågår."]),
    ], "DOC-MGMT-005", ["EVT-028"])

    mgmt("2025-10-31", "Rasmus Holm slutar – rekryterad av kund", [
        ("Rasmus Holms avgång", [
            "Rasmus Holm slutar 2025-10-31 och börjar hos kunden Skogsbygdens Energi AB.",
            "Intressekonflikt och konkurrensklausul diskuterades. Beslut: Rättslig bedömning av klausulens giltighet inhämtas från Krav & Klar; Sara tar ett relationssamtal med SEAB."]),
        ("Bemanning SE-Integration", ["Ersättning: Johan Wall går in på SE-Integration; rekrytering av senior utvecklare pågår."]),
    ], "DOC-MGMT-006", ["EVT-034"])

    mgmt("2025-11-08", "Kickoff produktutveckling", [
        ("ND-Intern plattform", [
            "Kickoff för intern produktutveckling (ND-Intern plattform). Budget 2,4 MSEK (lönekostnader), projektledare David Ekström.",
            "Team: Fredrik Lund, Elin Andersson, Johanna Sjöberg, deltid Tomas Berg. Första release planerad 2026-06."]),
        ("Övrigt", ["Årets kundundersökning skickas ut i december (Petra ansvarar)."]),
    ], "DOC-MGMT-007", ["EVT-036"])

    mgmt("2026-01-30", "AI-strategi och AI-policy", [
        ("AI-initiativ", [
            "Daniel Nyström presenterade förslag till internt AI-initiativ (ND-Intern AI).",
            "Beslut: Initiativet startas med budget 1,2 MSEK för 2026. Daniel är samordnare.",
            "Beslut: AI-policyn (DOC-POL-004) fastställs och gäller fr.o.m. 2026-02-01: källhänvisningskrav, mänsklig granskning, loggning och förbud mot känslig data i öppna modeller."]),
        ("Verktyg", ["Modellfabriken AB (API) och Analytics Cloud Inc godkänns som verktyg. Publika konsumenttjänster förbjuds för bolagsdata."]),
    ], "DOC-MGMT-008", ["EVT-044"], note="Beslutar AI-initiativ och fastställer DOC-POL-004.")

    mgmt("2026-08-20", "Kostnadsprogram inför FY27", [
        ("Kostnadsöversyn", [
            "Beslut: Kostnadsprogram inför FY27: (a) licensinventering av samtliga SaaS-verktyg (klar 2026-08-25), (b) utvärdering av underutnyttjade verktyg (Designsuiten 9 av 18 licenser används, Datainsikt 2 av 10), (c) pausad rekrytering med undantag för supportansvarig, (d) översyn av underkonsultanvändningen."]),
        ("Nordhost-driftstörningen", [
            "Jonas redogjorde för driftstörningen 2026-08-04 (6 timmar). SLA-ersättning diskuteras med Nordhost. Reservrutin för hosting saknas – åtgärdas i DR/BCP-planen."]),
        ("AI-incidenter", ["Daniel ska införa loggning av AI-användning före 2026-09-30."]),
    ], "DOC-MGMT-009", ["EVT-065"])

    mgmt("2026-09-15", "Uppsägning av BV-avtalet övervägs", [
        ("BV-Journalsystemet (Blåklintens Vård)", [
            "Bakgrund: tre kundklagomål om supportens svarstider under 2026, missad indexuppräkning per 2026-04-01 och långsamma betalningar.",
            "Alternativ: (a) säga upp avtalet senast 2026-09-30 (3 månaders uppsägning, avtalet löper till 2026-12-31) för omförhandling av pris och supportnivå, eller (b) behålla avtalet och åtgärda supportbemanningen.",
            "Beslut: Frågan skjuts upp till nästa ledningsmöte 2026-09-29. Underlag: lönsamhetskalkyl per kund samt förslag till ny prisnivå tas fram av Sara och Anders."]),
        ("Supportbemanning", ["Klara Månsson slutar 2026-09-30. Rekrytering av supportansvarig pågår (se DOC-EMP-010)."]),
    ], "DOC-MGMT-010", ["EVT-068"], note="BV-uppsägning (deadline 2026-09-30) skjuts upp till nästa möte.")

    # =====================================================================
    # BUDGET OCH PROGNOS
    # =====================================================================
    d = new_doc()
    head(d, "Budget FY2026 (2025-10-01 – 2026-09-30)", "Beslutad av styrelsen 2025-09-25",
         "Anders Bergström, CFO", "DOC-BUDG-001", "v1.0")
    para(d, "Sammanfattning")
    para(d, "Budgeten fastställer nettoomsättning 47 000 000 kr och EBIT-mål 7,0 % (3 290 000 kr). Målet är lägre än det faktiska utfallet kom att bli – vid budgettillfället förväntades inte den kraftiga volymökningen i SEAB-samarbetet (SE-Integration).")
    para(d, "Månadsbudget (belopp i tkr, netto)", bold=True)
    table(d, ["Månad", "Intäkter", "Kostnader", "EBIT"], [
        ["2025-10", "3 500", "3 550", "-50"],
        ["2025-11", "3 700", "3 650", "50"],
        ["2025-12", "3 200", "3 450", "-250"],
        ["2026-01", "3 700", "3 600", "100"],
        ["2026-02", "3 800", "3 650", "150"],
        ["2026-03", "3 900", "3 700", "200"],
        ["2026-04", "4 000", "3 750", "250"],
        ["2026-05", "4 100", "3 800", "300"],
        ["2026-06", "4 000", "3 700", "300"],
        ["2026-07", "3 200", "3 300", "-100"],
        ["2026-08", "4 300", "3 750", "550"],
        ["2026-09", "5 600", "3 810", "1 790"],
        ["Summa", "47 000", "43 710", "3 290 (7,0 %)"],
    ])
    para(d, "Kvartalsfördelning av budgeterade intäkter: Q1 (okt–dec) 10,4 MSEK, Q2 (jan–mar) 11,4 MSEK, Q3 (apr–jun) 12,1 MSEK, Q4 (jul–sep) 13,1 MSEK.")
    para(d, "Kostnadsbudget per kategori (tkr)", bold=True)
    table(d, ["Kategori", "Belopp"], [
        ["Personalkostnader", "29 200"],
        ["Underkonsulter", "4 400"],
        ["Lokaler", "2 160"],
        ["IT och mjukvara (SaaS)", "3 350"],
        ["Marknadsföring", "900"],
        ["Övriga externa kostnader", "3 700"],
        ["Summa", "43 710"],
    ])
    para(d, "Antaganden", bold=True)
    table(d, ["Antagande", "Kommentar"], [
        ["SE-Integration (SEAB)", "550–600 debiterbara timmar per månad till 1 180 kr/h. (Faktiskt utfall blev ca 600–800 timmar/månad.)"],
        ["Mossbackens Mekaniska", "Löpande samarbete hela året antogs. (Kunden lämnade oss 2026-06-30.)"],
        ["Rekryteringar", "Två planerade rekryteringar under året. (Båda sköts upp; endast arkitektrollen tillsattes i maj 2026.)"],
        ["Offentlig sektor", "Oförändrade volymer. (KL-Vårdportalen avslutades 2026-03.)"],
        ["TS-Produktionsportal", "Slutleverans 2026-03-31. (Blev 8 veckor försenad.)"],
    ])
    para(d, "Risker i budgeten: prispress hos SMB-kunder, beroende av enskilda konsulter samt indexklausuler som kräver aktiv faktureringshantering.")
    save(d, fol / "budget_fy2026.docx")
    reg("DOC-BUDG-001", "management/budget_fy2026.docx", "BUDGET",
        "Budget FY2026", "2025-09-25", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-008", "PRJ-002", "PRJ-009"],
        event_ids=["EVT-031"], valid_from="2025-10-01", valid_to="2026-09-30",
        note="Total 47,0 MSEK netto, EBIT-mål 7 % (3,29 MSEK). Q4 (jul–sep): 13,1 MSEK.")

    # -- DOC-BUDG-002 prognos ------------------------------------------------
    d = new_doc()
    head(d, "Reviderad helårsprognos FY2026", "Upprättad 2026-06-01",
         "Anders Bergström, CFO", "DOC-BUDG-002", "v2.0")
    para(d, "CFO presenterar reviderad helårsprognos enligt styrelsebeslut 2026-05-25. Prognosen ersätter tidigare prognos från mars (54,0 MSEK i basscenariot).")
    para(d, "Scenarier helåret FY2026 (nettoomsättning)", bold=True)
    table(d, ["Scenario", "Nettoomsättning (MSEK)", "EBIT-marginal", "Kommentar"], [
        ["Worst", "48,5", "9 %", "Ytterligare kundförluster, SU-vite, lägre SEAB-volymer Q4"],
        ["Bas", "52,5", "10 %", "SEAB-volymer i linje med maj-utfall; SU i tid"],
        ["Best", "55,0", "12 %", "SEAB-volymer fortsätter öka; nya ramavtal stängs i Q4"],
    ])
    para(d, "Utfall hittills (okt 2025–maj 2026)", bold=True)
    para(d, "Nettoomsättningen till och med maj uppgick till cirka 40,5 MSEK, vilket överstiger budget med cirka 10,6 MSEK. Överprestationen kommer från SEAB (SE-Integration ca 700–800 timmar/månad mot budgeterade 550–600) samt från SU-Produktionssystem och TR-Skogsportal, som inte fanns i budgeten.")
    para(d, "Förändringar mot tidigare prognos")
    para(d, "– Kundförlust: Mossbackens Mekaniska lämnade 2026-06-30 (MM-Underhållssystem, ca 1,0 MSEK/år).")
    para(d, "– Försening: TS-Produktionsportal 8 veckor försenad; viteförhandling pågår (kreditnota om 90 000 kr förväntas).")
    para(d, "– Motverkande: högre SEAB-volymer samt nya uppdrag (SU-Produktionssystem 1,95 MSEK, TR-Skogsportal 0,85 MSEK).")
    para(d, "Mest osäkra antaganden", bold=True)
    para(d, "1. SEAB-volymer under Q4 (jul–sep) – en minskning med 20 % motsvarar ca 1,1 MSEK lägre intäkter.")
    para(d, "2. Offentlig sektor – prognosen antar oförändrade volymer trots att KL-Vårdportalen avslutats.")
    para(d, "3. SU-Produktionssystem – risk för vite om 1 % per vecka (tak 10 % av 1,95 MSEK).")
    para(d, "4. Besparingar från licensinventeringen (först 2027-effekt).")
    save(d, fol / "prognos_fy2026.docx")
    reg("DOC-BUDG-002", "management/prognos_fy2026.docx", "PROGNOS",
        "Reviderad helårsprognos FY2026", "2026-06-01", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-008", "CUS-006", "PRJ-029"],
        version="2.0", event_ids=["EVT-059"], valid_from="2026-06-01",
        note="Bas 52,5 / worst 48,5 / best 55,0 MSEK; EBIT-marginal 9–12 %.")

    # =====================================================================
    # BANKMÖTEN
    # =====================================================================
    d = new_doc()
    head(d, "Bankmötesprotokoll – Norrvidden Bank AB", "Mötesdatum 2025-09-15",
         "Anders Bergström, CFO", "DOC-BANK-001", "v1.0")
    kv(d, "Närvarande", "Lena Pettersson (företagsrådgivare, Norrvidden Bank), Maja Lindqvist (VD), Anders Bergström (CFO)")
    para(d, "")
    para(d, "1. Likviditet och checkräkningskredit")
    para(d, "Banken noterade att checkräkningskrediten (limit 3 000 000 kr) varit utnyttjad som mest med 1 180 000 kr i mars 2025. Bolaget redovisade förbättrat kassaflöde under sommaren.")
    para(d, "2. Covenants")
    para(d, "Som villkor för förnyad checkkredit kräver banken: (a) kvartalsvis covenant-rapportering med soliditet ≥ 25 % och EBITDA > 0, (b) månatlig likviditetsprognos med 13 veckors sikt, (c) omedelbar information vid väsentliga kundförluster eller tvister.")
    para(d, "3. Beslut och åtgärder")
    table(d, ["Åtgärd", "Ansvarig", "Klart senast"], [
        ["Första covenant-rapport (Q4 FY25)", "Anders Bergström", "2025-11-15"],
        ["Månatlig likviditetsprognos införs", "Anders Bergström", "2025-10-01"],
        ["Underlag för förnyad kredit", "Lena Pettersson", "2026-02-28"],
    ])
    save(d, fol / "bankmote_2025-09-15.docx")
    reg("DOC-BANK-001", "management/bankmote_2025-09-15.docx", "PROTOKOLL",
        "Bankmötesprotokoll Norrvidden Bank (covenants)", "2025-09-15", "P-003",
        ["ORG-NORDVIKEN", "P-042"], event_ids=["EVT-030"],
        note="Covenants: soliditet ≥ 25 %, EBITDA > 0, månatlig likviditetsprognos.")

    d = new_doc()
    head(d, "Bankmötesprotokoll – Norrvidden Bank AB", "Mötesdatum 2026-03-20",
         "Anders Bergström, CFO", "DOC-BANK-002", "v1.0")
    kv(d, "Närvarande", "Lena Pettersson (företagsrådgivare, Norrvidden Bank), Anders Bergström (CFO)")
    para(d, "")
    para(d, "1. Förnyad checkräkningskredit")
    para(d, "Banken bekräftar förnyad checkräkningskredit om 3 000 000 kr till 2026-12-31 under förutsättning av fortsatt covenant-uppfyllelse.")
    para(d, "2. Covenant-status")
    para(d, "Soliditeten uppgick till 41 % per 2025-12-31 och EBITDA var positiv – båda covenants uppfyllda. Bolaget levererar månatliga likviditetsprognoser enligt överenskommelse.")
    para(d, "3. Bankens synpunkter")
    para(d, "Banken noterade kundkoncentrationen mot Skogsbygdens Energi (ca 35 % av omsättningen) och bad om återkoppling på spridningsplanen vid nästa möte (2026-06-15).")
    table(d, ["Åtgärd", "Ansvarig", "Klart senast"], [
        ["Återkoppling spridningsplan", "Maja Lindqvist", "2026-06-15"],
        ["Nästa covenant-rapport (Q2)", "Anders Bergström", "2026-05-15"],
    ])
    save(d, fol / "bankmote_2026-03-20.docx")
    reg("DOC-BANK-002", "management/bankmote_2026-03-20.docx", "PROTOKOLL",
        "Bankmötesprotokoll – förnyad checkkredit", "2026-03-20", "P-003",
        ["ORG-NORDVIKEN", "P-042"], event_ids=["EVT-052"],
        note="Checkkredit 3 MSEK förnyad t.o.m. 2026-12-31.")

    # =====================================================================
    # RISKREGISTER
    # =====================================================================
    d = new_doc()
    head(d, "Riskregister", "Upprättat 2024-12-20, senast uppdaterat 2026-05-11 (v3.2)",
         "Anders Bergström, CFO", "DOC-RISK-001", "v3.2")
    table(d, ["ID", "Risk", "Sannolikhet", "Konsekvens", "Ägare", "Åtgärd", "Status"], [
        ["R-01", "Kundkoncentration – SEAB (Skogsbygdens Energi, ca 35 % av omsättningen)", "Hög", "Kritisk", "Maja Lindqvist", "Spridningsplan, scenarioanalys (styrelsebeslut 2026-03-12), nya ENTERPRISE- och offentliga avtal", "Pågående"],
        ["R-02", "Nyckelpersonsberoende – Daniel Nyström (data/AI), Tomas Berg (arkitektur), Maria Gustavsson (testledning)", "Medel", "Hög", "–", "–", "Oåtgärdad"],
        ["R-03", "Obegränsat ansvar i ÖH-avtalet (CTR-2024-016, Örby Handel) – avviker från standardmallen", "Medel", "Hög", "Maja Lindqvist", "Nya avtal ska ha ansvarstak; tvisten om slutfakturan pågår", "Pågående"],
        ["R-04", "Vite i SU-avtalet (CTR-2026-001, Sundbygdens Varv): 1 %/vecka, tak 10 %", "Medel", "Medel", "Erik Norén", "Leveransplan med buffert, källkodsdepå hos tredje part", "Pågående"],
        ["R-05", "IT-beroende av Cloudserve Ireland (M365/Azure)", "Låg", "Hög", "Jonas Sandberg", "Exitplan och reservrutin utreds", "Delvis åtgärdad"],
        ["R-06", "Likviditet och kundfordringar", "Låg", "Hög", "Anders Bergström", "Veckovisa likviditetsavstämningar, påminnelserutin", "Åtgärdad (2025-10)"],
        ["R-07", "Personalomsättning i leveransteamet", "Medel", "Medel", "Petra Wahlgren", "Avslutssamtal, lönerevision, utvecklingssamtal", "Pågående"],
        ["R-08", "Integrationsfel lönesystem → ekonomisystem (Löneportalen)", "Medel", "Medel", "Jonas Sandberg", "Stabilisering med leverantören genomförd", "Åtgärdad (2026-01-15)"],
        ["R-09", "Tredjelandsöverföring av personuppgifter (Analytics Cloud Inc, USA)", "Medel", "Medel", "–", "SCC tecknade 2025-05-01; utökad användning bör undvikas", "Oåtgärdad"],
        ["R-10", "Intressekonflikt Kapellbacken Fastigheter (både kund och hyresvärd)", "Låg", "Medel", "–", "–", "Oåtgärdad"],
    ])
    para(d, "Kommentarer")
    para(d, "R-06: Per 2026-04-30 förelåg inga förfallna kundfordringar av betydelse. (Senast granskad 2026-04-30.)")
    para(d, "R-08: Senast verifierad 2026-01-15.")
    para(d, "Registret ses över halvårsvis. Nästa översyn: 2026-11 (med källhänvisningar enligt styrelsebeslut 2026-09-28).")
    save(d, fol / "riskregister.docx")
    reg("DOC-RISK-001", "management/riskregister.docx", "REGISTER",
        "Riskregister", "2026-05-11", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-009", "CUS-025", "CUS-016", "SUP-003", "SUP-013", "P-026", "P-011", "P-024"],
        version="3.2", event_ids=["EVT-008", "EVT-069"],
        note="Upprättat 2024-12-20; v3.2 2026-05-11. Tre risker utan ägare/åtgärd (R-02, R-09, R-10).")

    # =====================================================================
    # BOKSLUTSKOMMUNIKÉER
    # =====================================================================
    d = new_doc()
    head(d, "Bokslutskommuniké FY2025 (2024-10-01 – 2025-09-30)", "Publicerad 2025-11-24",
         "Anders Bergström, CFO", "DOC-FIN-001", "v1.0")
    para(d, "Nordviken Digital AB (559245-1673) redovisar härmed bokslutskommuniké för räkenskapsåret 2024-10-01 – 2025-09-30.")
    para(d, "Nettoomsättningen uppgick till 42 638 187 kr (42,6 MSEK). Rörelseresultatet uppgick till −209 936 kr och det finansiella nettot till −54 363 kr. Årets resultat efter skatt uppgick till −264 298 kr. Ingen bolagsskatt belastar året (underskottsavdrag utnyttjas framåt).")
    para(d, "Skogsbygdens Energi AB svarade för 27,8 % av omsättningen under året.")
    para(d, "Året präglades av lägre beläggning under våren, kundförluster och en tvistig slutfaktura mot Örby Handel & Logistik AB (96 800 kr inkl. moms hålls inne av kunden). Likviditeten var som mest ansträngd i mars, då checkräkningskrediten utnyttjades till 1 180 000 kr.")
    para(d, "Styrelsen föreslår att ingen utdelning lämnas för räkenskapsåret. Utdelningsfrågan skjuts till årsstämman.")
    para(d, "Årsstämma hålls i mars 2026. Årsredovisningen publiceras i november 2025 efter revision.")
    save(d, fol / "bokslutskommunike_fy2025.docx")
    reg("DOC-FIN-001", "management/bokslutskommunike_fy2025.docx", "RAPPORT",
        "Bokslutskommuniké FY2025", "2025-11-24", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-009"], event_ids=["EVT-032", "EVT-038"],
        note="Omsättning 42 638 187 kr; resultat efter skatt −264 298 kr; SEAB-andel 27,8 %.")

    d = new_doc()
    head(d, "Bokslutskommuniké FY2026 (2025-10-01 – 2026-09-30)", "Publicerad 2026-10-05",
         "Anders Bergström, CFO", "DOC-FIN-002", "v1.0")
    para(d, "Nordviken Digital AB (559245-1673) redovisar härmed bokslutskommuniké för räkenskapsåret 2025-10-01 – 2026-09-30. Samtliga belopp avser helåret.")
    para(d, "Nettoomsättningen uppgick till 54 310 278 kr, en ökning med 27 % jämfört med föregående år (42 638 187 kr). Ökningen förklaras främst av kraftigt ökade volymer i SEAB-samarbetet (SE-Integration) samt nya uppdrag (SU-Produktionssystem, TR-Skogsportal).")
    para(d, "Rörelseresultatet uppgick till 8 361 929 kr och det finansiella nettot till −11 932 kr. Resultatet före skatt uppgick till 8 349 997 kr. Skattekostnaden uppgick till 2 097 700 kr, varav 1 437 700 kr slutlig skatt och 360 000 kr preliminär skatt inbetald under året; underskottsavdraget från FY25 om 264 298 kr har utnyttjats. Årets resultat efter skatt uppgick till 6 252 297 kr.")
    para(d, "Skogsbygdens Energi AB svarade för 34,4 % av omsättningen under året (27,8 % föregående år).")
    para(d, "Likvida medel uppgick vid periodens utgång till 9 436 781 kr. Checkräkningskrediten var outnyttjad och banklånet slutamorterat under året. Kundfordringarna uppgick till 6 981 670 kr.")
    para(d, "Årets kundförluster: Sjöstadens Bryggeri AB försattes i konkurs 2025-12-08. September- och novemberfakturorna (totalt 220 065,00 kr inkl. moms) avskrevs som kundförlust 2025-12-31. Septemberfakturan hölls inne p.g.a. en reklamation och oktoberfakturan betalades sent (2025-11-20).")
    para(d, "Styrelsen har bordlagt utdelningsfrågan till årsstämman (november 2026), där styrelsens förslag presenteras tillsammans med investeringsbehoven för FY27.")
    save(d, fol / "bokslutskommunike_fy2026.docx")
    reg("DOC-FIN-002", "management/bokslutskommunike_fy2026.docx", "RAPPORT",
        "Bokslutskommuniké FY2026", "2026-10-05", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-010"], event_ids=["EVT-070"],
        note="Omsättning 54 310 278 kr; resultat 6 252 297 kr; SEAB 34,4 %; kassa 9 436 781 kr.")

    # =====================================================================
    # ÖVRIGA MANAGEMENTDOKUMENT
    # =====================================================================
    # -- Affärsplan 2026–2028 ------------------------------------------------
    d = new_doc()
    head(d, "Affärsplan 2026–2028", "Antagen av styrelsen 2026-03-12",
         "Maja Lindqvist, VD", "DOC-MGMT-011", "v1.0")
    para(d, "Strategiska mål", bold=True)
    table(d, ["Mål", "KPI", "Målvärde 2028", "Ägare"], [
        ["M1. Minska SEAB-beroendet", "SEAB:s andel av omsättningen", "≤ 25 %", "Maja Lindqvist, Sara Holm"],
        ["M2. Skala återkommande intäkter (förvaltning)", "Årlig förvaltningsintäkt", "15 MSEK/år", "Erik Norén"],
        ["M3. Tillväxt i offentlig sektor", "Offentlig omsättning", "+15 % per år", "Sara Holm"],
    ])
    para(d, "Marknadsantaganden", bold=True)
    para(d, "– Offentlig sektor bedöms växa med 15 % per år drivet av digitaliseringssatsningar hos kommuner och regioner.")
    para(d, "– Enterprise-segmentet växer måttligt (5–8 %/år); SMB-marknaden är prispressad.")
    para(d, "– AI-tjänster (dataanalys, generativ AI) bedöms bli en ny intäktskälla från 2027.")
    para(d, "Stödinitiativ")
    table(d, ["Initiativ", "Budget", "Ägare"], [
        ["ND-Intern AI-initiativ", "1,2 MSEK (2026)", "Daniel Nyström"],
        ["ND-Intern plattform (produktutveckling)", "2,4 MSEK", "David Ekström"],
        ["Förvaltningspaketering (M2)", "–", "–"],
        ["Enterprise-försäljning väst", "0,5 MSEK/år", "Sara Holm"],
        ["Kontor Göteborg (utvärderas)", "Se kalkyl DOC-MGMT-014", "Maja Lindqvist"],
    ])
    para(d, "Uppföljning: Målen följs upp kvartalsvis i KPI-rapporten och vid styrelsemöten.")
    save(d, fol / "affarsplan_2026_2028.docx")
    reg("DOC-MGMT-011", "management/affarsplan_2026_2028.docx", "RAPPORT",
        "Affärsplan 2026–2028", "2026-03-12", "P-001",
        ["ORG-NORDVIKEN", "CUS-001", "PRJ-090", "PRJ-091"],
        event_ids=["EVT-051"],
        note="Antagande: offentlig sektor växer 15 %/år. Faktisk offentlig omsättning minskade (KL-Vårdportal avslutad 2026-03).")

    # -- KPI-rapport sep 2026 --------------------------------------------------
    d = new_doc()
    head(d, "KPI-rapport – september 2026", "Upprättad 2026-10-05",
         "Anders Bergström, CFO", "DOC-MGMT-012", "v1.0")
    table(d, ["KPI", "Utfall sep", "Mål", "Status", "Kommentar"], [
        ["Beläggning leveransteamet", "88 %", "≥ 82 %", "OK", "Förbättrad efter sommaren"],
        ["Debiteringsgrad", "91 %", "≥ 90 %", "OK", ""],
        ["Sjukfrånvaro (rullande 12 mån)", "4,4 %", "≤ 4 %", "Avvikelse", "Leveransteamet högre (se HR-rapport)"],
        ["Kundnöjdhet (NPS)", "38", "≥ 40", "Avvikelse", "BV-klagomål drar ned"],
        ["Pipeline (öppen)", "13,4 MSEK", "≥ 12 MSEK", "OK", "Varav committed 10,8 MSEK"],
        ["SaaS-kostnad per månad", "259 tkr", "≤ 240 tkr", "Avvikelse", "Licensinventering pågår"],
        ["Kundfordringar förfallna", "Se reskontra", "0", "Avvikelse", "Blåklintens Vård, Stormvindens Logistik"],
    ])
    para(d, "Prognos Q4 (jul–sep, avslutat kvartal): nettoomsättningen för Q4 beräknas till 12,4 MSEK. Prognosen för helåret bekräftas till cirka 54 MSEK netto.")
    para(d, "Not: Rapporten sammanställs manuellt varje vecka (ca 4 timmar) och distribueras till ledningsgruppen; i praktiken används den främst inför styrelsemöten.")
    save(d, fol / "kpi_rapport_sep2026.docx")
    reg("DOC-MGMT-012", "management/kpi_rapport_sep2026.docx", "RAPPORT",
        "KPI-rapport september 2026", "2026-10-05", "P-003",
        ["ORG-NORDVIKEN", "CUS-007", "CUS-049"],
        note="Q4-prognos 12,4 MSEK (jämför budget 13,1 MSEK och pipeline-committed 10,8 MSEK).")

    # -- Likviditetsprognos Q4 -------------------------------------------------
    d = new_doc()
    head(d, "Likviditetsprognos Q4 (okt–dec 2026)", "Upprättad 2026-09-30",
         "Anders Bergström, CFO", "DOC-MGMT-013", "v1.0")
    table(d, ["Vecka", "Inbetalningar", "Utbetalningar", "Utgående likviditet (kassa + kredit)"], [
        ["v41 (5–9 okt)", "2 100 000", "1 350 000", "11 434 000"],
        ["v42 (12–16 okt)", "1 800 000", "1 420 000", "11 814 000"],
        ["v43 (19–23 okt)", "1 900 000", "1 380 000", "12 334 000"],
        ["v44 (26–30 okt)", "1 750 000", "1 450 000", "12 634 000"],
        ["v45–v48 (nov)", "7 200 000", "6 100 000", "13 734 000"],
        ["v49–v52 (dec)", "6 800 000", "6 900 000", "13 634 000"],
    ])
    para(d, "Antaganden: SEAB betalar enligt 30 dagar; Blåklintens Vård och Stormvindens Logistik antas betala 30–45 dagar sent; skattebetalning 1 437 700 kr i december; inga större investeringar under perioden.")
    para(d, "Covenants: Q4-rapport till banken senast 2026-11-15 (soliditet, EBITDA). Checkkrediten (3 MSEK) förväntas inte behöva utnyttjas.")
    save(d, fol / "likviditetsprognos_q4_2026.docx")
    reg("DOC-MGMT-013", "management/likviditetsprognos_q4_2026.docx", "RAPPORT",
        "Likviditetsprognos Q4 2026", "2026-09-30", "P-003",
        ["ORG-NORDVIKEN", "CUS-001", "CUS-007", "CUS-049"])

    # -- Investeringskalkyl kontor Göteborg -------------------------------------
    d = new_doc()
    head(d, "Investeringskalkyl – nytt kontor Göteborg", "Upprättad 2026-04-30",
         "Anders Bergström, CFO", "DOC-MGMT-014", "v1.0")
    para(d, "Förutsättningar: nytt kontor i Göteborg med 6 konsulter. Hyra 110 000 kr/mån, inredning 1 200 000 kr (engångs), rekrytering/onboarding 700 000 kr (engångs). Årlig investeringstakt (utrustning, vidareutbildning, rekrytering): 1,6 MSEK per år.")
    para(d, "Intäktsramp (debiterbar omsättning per månad, tkr)", bold=True)
    table(d, ["Månad", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10–12"], [
        ["Intäkter", "0", "0", "150", "300", "450", "550", "650", "750", "900", "950"],
    ])
    para(d, "Löpande kostnader per månad: hyra 110 000 + löner 6 × 75 000 (450 000) + övrigt 40 000 = 600 000 kr.")
    para(d, "Break-even: första månad med positivt månadsresultat är månad 9 (intäkter 900 000 kr > kostnader 600 000 kr).")
    para(d, "Kassaflöde (tkr, kumulativt): −600, −1 200, −1 650, −1 950, −2 100, −2 150, −2 100, −1 950, −1 650, −1 300, −950, −600 (månad 1–12). Återbetalning av engångsinvesteringarna (1,9 MSEK) beräknas till månad 26.")
    para(d, "Beslutspunkt: Styrelsebeslut krävs (investering > 500 000 kr enligt VD-instruktionen). Beslut föreslås vid styrelsemötet 2026-11-26.")
    save(d, fol / "investeringskalkyl_goteborg.docx")
    reg("DOC-MGMT-014", "management/investeringskalkyl_goteborg.docx", "KALKYL",
        "Investeringskalkyl kontor Göteborg", "2026-04-30", "P-003",
        ["ORG-NORDVIKEN"], note="Capex 1,6 MSEK/år; break-even månad 9.")

    # -- Bilkalkyl lease vs köp --------------------------------------------------
    d = new_doc()
    head(d, "Bilkalkyl – tjänstebilar: leasing vs köp", "Upprättad 2026-06-15",
         "Anders Bergström, CFO", "DOC-MGMT-015", "v1.0")
    para(d, "Nuvarande leasingavtal (2 bilar, 12 800 kr/mån, CTR-SUP-029) löper ut 2026-11-30. Två offerter har inhämtats:")
    table(d, ["Post", "Leasing (Billotsen AB)", "Köp (Datorlagret partner)"], [
        ["Månadskostnad per bil", "6 950 kr", "–"],
        ["Inköpspris per bil", "–", "389 000 kr"],
        ["Restvärde efter 36 mån", "–", "45 % (175 050 kr/bil)"],
        ["Service", "Ingår", "8 000 kr/år och bil"],
        ["Försäkring", "9 500 kr/år och bil", "9 500 kr/år och bil"],
    ])
    para(d, "Kalkyl 36 månader (2 bilar):")
    para(d, "Leasing: 36 × 13 900 = 500 400 kr (service ingår).")
    para(d, "Köp: 778 000 − 350 100 (restvärde) + 48 000 (service) + 57 000 (försäkring) + cirka 48 000 (ränta) = cirka 580 900 kr.")
    para(d, "Rekommendation: Leasing är cirka 80 500 kr billigare över 36 månader och ger lägre kapitalbindning. Beslut fattas av VD (under 500 000 kr per beslut).")
    save(d, fol / "bilkalkyl_lease_vs_kop.docx")
    reg("DOC-MGMT-015", "management/bilkalkyl_lease_vs_kop.docx", "KALKYL",
        "Bilkalkyl leasing vs köp", "2026-06-15", "P-003",
        ["ORG-NORDVIKEN", "SUP-029"])

    # -- Produktutvecklingscase ---------------------------------------------------
    d = new_doc()
    head(d, "Produktutvecklingscase – ND-Intern plattform", "Upprättad 2026-09-15",
         "David Ekström, projektledare", "DOC-MGMT-016", "v1.1")
    para(d, "Budget FY2025/26: 2 400 000 kr (lönekostnader). Förbrukat t.o.m. 2026-08: 1 850 000 kr.")
    table(d, ["Milstolpe", "Plan", "Utfall", "Status"], [
        ["Designklar", "2026-02", "2026-03", "Klar"],
        ["MVP klar", "2026-06", "2026-06", "Klar"],
        ["Intern pilot (2 team)", "2026-08", "2026-09", "Pågår"],
        ["Produktifiering", "2026-12", "–", "Ej startad"],
    ])
    para(d, "KPI: intern effektivitet (rapporttid −15 %), licenskostnader per konsult.")
    para(d, "Risk: nyckelpersonsberoende (Daniel Nyström ensam data/AI-kompetens sedan Lukas Ek lämnade 2026-05-31).")
    para(d, "Beslutspunkt: fortsatt fas 2 (budget 1,6 MSEK FY27) föreslås till styrelsen 2026-11-26.")
    save(d, fol / "produktutvecklingscase_nd_intern.docx")
    reg("DOC-MGMT-016", "management/produktutvecklingscase_nd_intern.docx", "RAPPORT",
        "Produktutvecklingscase ND-Intern plattform", "2026-09-15", "P-008",
        ["PRJ-090", "P-026"], version="1.1", event_ids=["EVT-036"],
        note="Budget 2,4 MSEK; förbrukat 1,85 MSEK t.o.m. 2026-08.")

    # -- Värderingsmemo -----------------------------------------------------------
    d = new_doc()
    head(d, "Värderingsmemo – Nordviken Digital AB", "Upprättad 2026-09-15",
         "Anders Bergström, CFO", "DOC-MGMT-017", "v1.0")
    para(d, "Syfte: internt underlag inför styrelsens diskussion om utdelning och eventuellt delägarskifte.")
    para(d, "DCF (evighetsvärde)", bold=True)
    table(d, ["Antagande", "Värde"], [
        ["EBIT 2026 (normaliserad)", "8 600 000 kr"],
        ["Skatt", "20,6 %"],
        ["Investeringar (netto)", "1 200 000 kr/år"],
        ["Fritt kassaflöde", "5 900 000 kr"],
        ["WACC", "12 %"],
        ["Evig tillväxt", "4 %"],
        ["EV (DCF)", "5,9 / (0,12 − 0,04) ≈ 73,8 MSEK"],
    ])
    para(d, "Multipelvärdering: EV/EBIT 8–10× på 8,6 MSEK ger 68,8–86,0 MSEK.")
    para(d, "Känslighet: om SEAB-beroendet (34,4 %) prissätts med rabatt om 15 % sjunker värdet till cirka 63–73 MSEK. Vid kundförlust SEAB (scenario: −35 % EBIT) faller värdet till cirka 45–55 MSEK.")
    para(d, "Slutsats: värdeintervall 60–85 MSEK i basscenariot, med nyckelrisk i kundkoncentrationen.")
    save(d, fol / "varderingsmemo.docx")
    reg("DOC-MGMT-017", "management/varderingsmemo.docx", "MEMO",
        "Värderingsmemo", "2026-09-15", "P-003",
        ["ORG-NORDVIKEN", "CUS-001"], note="DCF + multipel; antaganden explicit angivna.")


def section_correspondence(m: Model) -> None:
    fol = F["correspondence"]

    def mail(doc_id, path_stem, thread, title, created, evt, note=""):
        p = fol / (path_stem + ".eml")
        eml_w(p, thread)
        reg(doc_id, f"correspondence/{path_stem}.eml", "MAIL", title, created,
            "P-005", ["ORG-NORDVIKEN"], event_ids=evt, note=note)

    # -- DOC-MAIL-001 Gustav Pettersson ------------------------------------
    mail("DOC-MAIL-001", "mail_2024-11-15_gustav_pettersson_uppsagning",
        [dict(from_="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              to="Eva Granlund <eva.granlund@example.se>; Jonas Sandberg <jonas.sandberg@nordvikendigital.se>",
              date=dt("2024-11-15"), subject="Gustav Pettersson – uppsägning och konkurrensklausul",
              body=("Hej,\n\nGustav Pettersson har sagt upp sig och börjar hos Blå Ocean IT AB den 1 december.\n"
                    "I hans anställningsavtal finns en konkurrensklausul på 12 månader. Jag vill att vi "
                    "tar en rättslig bedömning av om klausulen håller innan vi agerar.\n\n"
                    "Föreslår att Krav & Klar tittar på detta.\n\nMed vänlig hälsning\nMaja")),
         dict(from_="Fredrik Stenberg <fredrik.stenberg@example.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2024-11-18"), subject="SV: Gustav Pettersson – uppsägning och konkurrensklausul",
              body=("Hej Maja,\n\nKlausulen är kortfattat formulerad och saknar tydligt syfte och kompensation. "
                    "Min preliminära bedömning är att den är svår att göra gällande. Jag återkommer med "
                    "skriftlig bedömning och förslag till ny malltext.\n\nFredrik Stenberg, Advokatfirman Krav & Klar"))],
        "E-posttråd: Gustav Petterssons uppsägning och konkurrensklausul", "2024-11-18", ["EVT-004"])

    # -- DOC-MAIL-002 NH-klagomål -------------------------------------------
    mail("DOC-MAIL-002", "mail_2024-12-18_nh_prestandaklagomal",
        [dict(from_="Nina Ekström <nina.ekstrom@example.se>",
              to="Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2024-12-18"), subject="NH-Logistikportalen – prestanda igen",
              body=("Hej Sara,\n\nNu måste vi tyvärr ta upp prestandan i NH-Logistikportalen för tredje gången. "
                    "Svarstiderna i godsmottagningen är 6–8 sekunder på eftermiddagarna och våra operatörer "
                    "tappar flöde. Vi behöver en åtgärdsplan den här gången, inte bara en förklaring.\n\nNina Ekström, Norrhamns Hamn")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Nina Ekström <nina.ekstrom@example.se>",
              cc="Erik Norén <erik.noren@nordvikendigital.se>",
              date=dt("2024-12-19"), subject="SV: NH-Logistikportalen – prestanda igen",
              body=("Hej Nina,\n\nVi beklagar att problemet återkommit. Erik Norén (leveranschef) och jag föreslår "
                    "ett möte redan i morgon för att gå igenom åtgärdsplanen: prestandatest i er miljö, "
                    "hotfix senast 31 januari samt månatliga prestandarapporter framöver.\n\nMed vänlig hälsning\nSara Holm"))],
        "E-posttråd: NH-Logistikportalen prestandaklagomål (tredje gången)", "2024-12-19", ["EVT-007"])

    # -- DOC-MAIL-003 ÖH-tvist ------------------------------------------------
    mail("DOC-MAIL-003", "mail_2025-02-28_oh_slutfaktura_tvist",
        [dict(from_="Nina Ekström <nina.ekstrom@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2025-02-28"), subject="Slutfaktura ÖH-Webbplattform – vi bestrider del av beloppet",
              body=("Hej Anders,\n\nVi har mottagit slutfakturan på 625 000 kr inkl. moms för ÖH-Webbplattformen. "
                    "Vi bestrider 96 800 kr inkl. moms på grund av kvarstående acceptansanmärkningar "
                    "(rapportmodulen levererar inte enligt specifikation). Vi betalar 528 200 kr i dag och "
                    "håller inne resterande belopp tills anmärkningarna är åtgärdade.\n\nNina Ekström, Örby Handel & Logistik AB")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Nina Ekström <nina.ekstrom@example.se>",
              cc="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2025-03-03"), subject="SV: Slutfaktura ÖH-Webbplattform – vi bestrider del av beloppet",
              body=("Hej Nina,\n\nVi noterar att ni betalar 528 200 kr och håller inne 96 800 kr. Vi delar inte "
                    "er bedömning att rapportmodulen avviker från specifikationen och vill ha en gemensam "
                    "genomgång av anmärkningarna. Vi återkommer med förslag på mötestid.\n\nAnders Bergström"))],
        "E-posttråd: ÖH-Webbplattform tvistig slutfaktura", "2025-03-03", ["EVT-014"])

    # -- DOC-MAIL-004 Tobias avsked -------------------------------------------
    mail("DOC-MAIL-004", "mail_2025-03-14_tobias_lindqvist_avsked",
        [dict(from_="Petra Wahlgren <petra.wahlgren@nordvikendigital.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2025-03-14"), subject="Tobias Lindqvist – avsked genomfört",
              body=("Hej Maja,\n\nAvskedandet av Tobias Lindqvist är genomfört i dag med stöd av bristande "
                    "prestation efter upprepade uppföljningssamtal. Facket har kontaktat oss och bestrider "
                    "uppsägningen. Vi förbereder dokumentationen (se DOC-HR-003).\n\nPetra")),
         dict(from_="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              to="Petra Wahlgren <petra.wahlgren@nordvikendigital.se>",
              cc="Fredrik Stenberg <fredrik.stenberg@example.se>",
              date=dt("2025-03-15"), subject="SV: Tobias Lindqvist – avsked genomfört",
              body=("Tack Petra. Krav & Klar tar förhandlingarna med motpartens ombud. Vi håller låg profil "
                    "externt tills processen är klar.\n\nMaja"))],
        "E-posttråd: Avsked av Tobias Lindqvist", "2025-03-15", ["EVT-016"])

    # -- DOC-MAIL-005 ÖH lämnar -------------------------------------------------
    mail("DOC-MAIL-005", "mail_2025-03-31_oh_avslutar_samarbetet",
        [dict(from_="Nina Ekström <nina.ekstrom@example.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2025-03-31"), subject="Örby Handel & Logistik avslutar samarbetet",
              body=("Hej Maja,\n\nVi har beslutat att avsluta samarbetet med Nordviken Digital per 31 mars. "
                    "Bakgrunden är den olösta tvisten om ÖH-Webbplattformen och att vi inte ser att vi "
                    "kommer vidare tillsammans. Vi behåller vårt ställningstagande avseende det innehållna "
                    "beloppet.\n\nNina Ekström")),
         dict(from_="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              to="Nina Ekström <nina.ekstrom@example.se>",
              date=dt("2025-04-01"), subject="SV: Örby Handel & Logistik avslutar samarbetet",
              body=("Hej Nina,\n\nVi beklagar beslutet. Vi anser fortsatt att våra leveranser uppfyller "
                    "specifikationen och vill gärna nå en överenskommelse om det innehållna beloppet även "
                    "om samarbetet upphör.\n\nMed vänlig hälsning\nMaja Lindqvist"))],
        "E-posttråd: Örby Handel avslutar samarbetet", "2025-04-01", ["EVT-017"])

    # -- DOC-MAIL-006 Förlikningsförhandling --------------------------------------
    mail("DOC-MAIL-006", "mail_2025-04-15_forlikning_tobias",
        [dict(from_="Fredrik Stenberg <fredrik.stenberg@example.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2025-04-15"), subject="Förlikning Tobias Lindqvist – lägesrapport",
              body=("Hej Maja,\n\nFörlikningsförhandlingarna pågår. Tobias ombud har lämnat ett motbud om "
                    "6 månadslöner. Vår bedömning är att en uppgörelse kring 3–4 månadslöner är realistisk "
                    "och klart billigare än en tvist. Jag återkommer med en rekommendation.\n\nFredrik Stenberg"))],
        "E-posttråd: Förlikningsförhandling Tobias Lindqvist", "2025-04-15", ["EVT-020"])

    # -- DOC-MAIL-007 Gråvikens index ---------------------------------------------
    mail("DOC-MAIL-007", "mail_2025-10-01_gv_indexupprakning",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>; Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2025-10-01"), subject="Gråvikens kommun – indexuppräkning per 1 oktober",
              body=("Hej,\n\nEnligt ramavtalet med Gråvikens kommun (CTR-2022-007) ska timpriset räknas upp "
                    "med KPI per 2025-10-01 (bas 2023-10). Vi fakturerar fortfarande 1 050 kr/h i stället "
                    "för cirka 1 075 kr/h. Jag lägger ett ärende hos Sara så att debiteringsunderlaget "
                    "justeras inför novemberfakturan.\n\nAnders")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2025-10-03"), subject="SV: Gråvikens kommun – indexuppräkning per 1 oktober",
              body=("Tack Anders, jag tar det med ekonomisystemet så snart det finns utrymme – just nu är det "
                    "fullt fokus på KF-debiteringen och SEAB-fakturorna. Återkommer.\n\nSara"))],
        "E-posttråd: Gråvikens kommun indexuppräkning (ärendet rann ut i sanden)", "2025-10-03", ["EVT-033"],
        note="Indexuppräkningen per 2025-10-01 har inte tillämpats i faktureringen.")

    # -- DOC-MAIL-008 KF underbilling ---------------------------------------------
    mail("DOC-MAIL-008", "mail_2025-11-01_kf_debiteringsunderlag",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Erik Norén <erik.noren@nordvikendigital.se>",
              date=dt("2025-11-01"), subject="KF-Biljettsystem – debiteringsunderlag november",
              body=("Hej Erik,\n\nHär kommer debiteringsunderlaget för KF-Biljettsystem för november. "
                    "Observera att timpriset fr.o.m. november enligt underlaget ligger kvar på 1 050 kr/h.\n\nAnders")),
         dict(from_="Erik Norén <erik.noren@nordvikendigital.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2025-11-01"), subject="SV: KF-Biljettsystem – debiteringsunderlag november",
              body=("Hej Anders,\n\nOK. Jag noterar att avtalet medger en indexuppräkning till 1 150 kr/h per "
                    "2025-11-01 – borde vi inte ta med den? Återkom gärna.\n\nErik")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Erik Norén <erik.noren@nordvikendigital.se>",
              date=dt("2025-11-02"), subject="SV: KF-Biljettsystem – debiteringsunderlag november",
              body=("Hej Erik,\n\nRimlig fråga – jag tittar på indexklausulen och återkommer. Kör på 1 050 tills "
                    "vidare så fakturan inte blir sen.\n\nAnders"))],
        "E-posttråd: KF-Biljettsystem debiteringsunderlag (indexhöjning ej debiterad)", "2025-11-02", ["EVT-035"],
        note="Höjningen till 1 150 kr/h debiterades först fr.o.m. 2026-02; eftersläpningsfaktura 2026-02-28.")

    # -- DOC-MAIL-009 Sjöstadens konkurs -------------------------------------------
    mail("DOC-MAIL-009", "mail_2025-12-08_sjostadens_konkurs",
        [dict(from_="Carl Broman <carl.broman@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2025-12-08"), subject="Sjöstadens Bryggeri AB i konkurs – bevakning av fordran",
              body=("Hej,\n\nJag har utsetts till konkursförvaltare för Sjöstadens Bryggeri AB (konkursbeslut "
                    "i dag). Ni har obetalda fakturor om totalt 220 065,00 kr inkl. moms (september och "
                    "november). Anmäl er fordran i boet senast 2025-12-22 via formuläret i bifogad fil.\n\n"
                    "Carl Broman, konkursförvaltare")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Carl Broman <carl.broman@example.se>",
              cc="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2025-12-09"), subject="SV: Sjöstadens Bryggeri AB i konkurs – bevakning av fordran",
              body=("Hej Carl,\n\nVi bevakar fordringarna (220 065,00 kr totalt) i boet. Notera att "
                    "septemberfakturan hölls inne av kunden p.g.a. en reklamation, och oktoberfakturan "
                    "betalades sent, den 20 november.\n\nAnders Bergström"))],
        "E-posttråd: Sjöstadens Bryggeri i konkurs", "2025-12-09", ["EVT-039"])

    # -- DOC-MAIL-010 KF upptäckt ---------------------------------------------------
    mail("DOC-MAIL-010", "mail_2026-02-10_kf_underfakturering_upptackt",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>; Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2026-02-10"), subject="KF-Biljettsystem – vi har fakturerat fel timpris sedan november",
              body=("Hej,\n\nJag upptäckte i dag att KF-Biljettsystem fakturerats med 1 050 kr/h i stället "
                    "för avtalade 1 150 kr/h sedan 2025-11-01. Det beror på att debiteringsunderlaget inte "
                    "uppdaterades. Differensen uppgår till 53 730 kr exkl. moms (100 kr × fakturerade timmar "
                    "nov–jan).\n\nJag föreslår en eftersläpningsfaktura till kunden per 2026-02-28 och en "
                    "kontroll så att inga fler avtal har missade indexuppräkningar.\n\nAnders")),
         dict(from_="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-02-10"), subject="SV: KF-Biljettsystem – vi har fakturerat fel timpris sedan november",
              body=("Bra fångat. Genomför eftersläpningsfakturan och redovisa kontrollen av övriga avtal på "
                    "nästa ledningsmöte.\n\nMaja"))],
        "E-posttråd: KF-underfakturering upptäckt", "2026-02-10", ["EVT-046"])

    # -- DOC-MAIL-011 Mossbacken säger upp -------------------------------------------
    mail("DOC-MAIL-011", "mail_2026-03-26_mossbacken_uppsagning",
        [dict(from_="Roger Lund <roger.lund@example.se>",
              to="Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2026-03-26"), subject="MM-Underhållssystem – uppsägning",
              body=("Hej Sara,\n\nVi säger härmed upp avtalet för MM-Underhållssystem med tre månaders "
                    "uppsägningstid, dvs. till 2026-06-30. Vi har fått ett erbjudande från en annan "
                    "leverantör som ligger cirka 20 % lägre i pris för motsvarande tjänst. Kan ni möta den "
                    "prisnivån hör vi gärna av oss innan dess.\n\nRoger Lund, Mossbackens Mekaniska")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2026-03-26"), subject="VB: MM-Underhållssystem – uppsägning",
              body=("Hej Maja,\n\nMossbacken säger upp – konkurrenten ligger 20 % lägre. Vi kan inte möta det "
                    "priset utan att gå back. Jag föreslår att vi accepterar och fokuserar på en bra "
                    "överlämning.\n\nSara"))],
        "E-posttråd: Mossbackens Mekaniska säger upp MM-Underhållssystem", "2026-03-26", ["EVT-053"])

    # -- DOC-MAIL-012 BV index --------------------------------------------------------
    mail("DOC-MAIL-012", "mail_2026-04-01_bv_indexupprakning",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2026-04-01"), subject="Blåklintens Vård – indexuppräkning per 1 april",
              body=("Hej Sara,\n\nAvtalet med Blåklintens Vård (CTR-2023-018) medger KPI-uppräkning per "
                    "2026-04-01 (bas 2024-04): 990 kr/h blir cirka 1 009 kr/h. Faktureringen ligger kvar på "
                    "990. Motsvarande det som hände med KF i februari – vi bör rätta till detta direkt.\n\nAnders")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-04-02"), subject="SV: Blåklintens Vård – indexuppräkning per 1 april",
              body=("Hej Anders,\n\nHåller med, men kunden är redan irriterad över svarstiderna i supporten "
                    "och betalar sent. Jag vill inte lägga en prishöjning ovanpå det just nu. Kan vi skjuta "
                    "på det till efter sommaren?\n\nSara"))],
        "E-posttråd: Blåklintens Vård indexuppräkning (skjuten på framtiden)", "2026-04-02", ["EVT-054"],
        note="Indexuppräkningen per 2026-04-01 har inte tillämpats i faktureringen.")

    # -- DOC-MAIL-013 TS förlikning -----------------------------------------------------
    mail("DOC-MAIL-013", "mail_2026-06-30_ts_forlikning",
        [dict(from_="Ola Persson <ola.persson@example.se>",
              to="Karin Olsson <karin.olsson@nordvikendigital.se>",
              date=dt("2026-06-30"), subject="TS-Produktionsportal – förlikningsförslag",
              body=("Hej Karin,\n\nEfter vårt samtal i dag bekräftar jag förlikningsförslaget: en kreditnota "
                    "på 90 000 kr inkl. moms (motsvarande 50 % av det avtalsenliga vitet) mot att vi ger "
                    "slutacceptans av TS-Produktionsportalen. Skicka kreditnotan så godkänner vi formellt.\n\nOla Persson, Timmervikens Såg")),
         dict(from_="Karin Olsson <karin.olsson@nordvikendigital.se>",
              to="Ola Persson <ola.persson@example.se>",
              cc="Anders Bergström <anders.bergstrom@nordvikendigital.se>; Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2026-06-30"), subject="SV: TS-Produktionsportal – förlikningsförslag",
              body=("Hej Ola,\n\nÖverenskommet. Kreditnota 90 000 kr utfärdas i dag och slutacceptans "
                    "registreras. Tack för ett konstruktivt samtal.\n\nKarin Olsson"))],
        "E-posttråd: TS-Produktionsportal förlikning (kreditnota 90 000 kr)", "2026-06-30", ["EVT-061"])

    # -- DOC-MAIL-014 BV klagomål --------------------------------------------------------
    mail("DOC-MAIL-014", "mail_2026-09-10_bv_klagomal_svarstider",
        [dict(from_="Ingrid Holm <ingrid.holm@example.se>",
              to="Sara Holm <sara.holm@nordvikendigital.se>",
              date=dt("2026-09-10"), subject="Supportärenden BV-Journalsystem – svarstider",
              body=("Hej Sara,\n\nNu måste jag tyvärr ta upp supportens svarstider igen – tredje gången i år. "
                    "Vårt senaste ärende låg obesvarat i 14 dagar, och det gällde en blockerad "
                    "journalhantering. Vi behöver en åtgärdsplan med namn på vem som ansvarar.\n\nIngrid Holm, Blåklintens Vård")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Ingrid Holm <ingrid.holm@example.se>",
              date=dt("2026-09-12"), subject="SV: Supportärenden BV-Journalsystem – svarstider",
              body=("Hej Ingrid,\n\nVi ber om ursäkt. Vi rekryterar just nu en ny supportansvarig (vår "
                    "tidigare har slutat) och har tillfälligt förstärkt med två utvecklare. Jag återkommer "
                    "senast fredag med en åtgärdsplan och en namngiven kontaktperson.\n\nSara Holm"))],
        "E-posttråd: BV-Journalsystem klagomål om svarstider (tredje gången 2026)", "2026-09-12", ["EVT-067"])

    # -- DOC-MAIL-015 bank correspondence ------------------------------------------------
    mail("DOC-MAIL-015", "mail_2025-10-03_bank_covenants",
        [dict(from_="Lena Pettersson <lena.pettersson@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2025-10-03"), subject="Covenant-rapportering – mall och tidplan",
              body=("Hej Anders,\n\nBifogar mallen för kvartalsrapporteringen (soliditet, EBITDA) samt "
                    "tidplanen. Första rapporten avser Q4 (jul–sep) och ska vara oss tillhanda senast "
                    "2025-11-15. Likviditetsprognosen ska skickas månadsvis senast den 5:e.\n\nMed vänlig hälsning\nLena Pettersson, Norrvidden Bank")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Lena Pettersson <lena.pettersson@example.se>",
              date=dt("2025-10-06"), subject="SV: Covenant-rapportering – mall och tidplan",
              body=("Hej Lena,\n\nTack. Vi kör enligt tidplanen – första rapporten kommer senast 2025-11-15.\n\nAnders"))],
        "E-posttråd: Bank – covenant-rapportering", "2025-10-06", ["EVT-030"])

    # -- DOC-MAIL-016 inkassokrav Blåklinten ------------------------------------------------
    mail("DOC-MAIL-016", "mail_2026-05-08_inkasso_blaklinten",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Ingrid Holm <ingrid.holm@example.se>",
              date=dt("2026-05-08"), subject="Obetalda fakturor – inkassovarning",
              body=("Hej Ingrid,\n\nVi har inte mottagit betalning för fakturorna 2026-0081 (74 250 kr, "
                    "förfallen 2026-04-15) och 2026-0042 (68 900 kr, förfallen 2026-03-30). Påminnelse 1 och "
                    "2 har skickats utan svar.\n\nOm betalning inte inkommit inom 10 dagar överlämnas "
                    "fordringarna till inkasso. Kontakta mig gärna om ni behöver en avbetalningsplan.\n\nAnders Bergström"))],
        "E-posttråd: Inkassokrav Blåklintens Vård", "2026-05-08", [])

    # -- DOC-MAIL-017 KF fakturafel intern tråd ---------------------------------------------
    mail("DOC-MAIL-017", "mail_2026-02-12_kf_fakturafel_intern",
        [dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>; Erik Norén <erik.noren@nordvikendigital.se>",
              date=dt("2026-02-12"), subject="KF eftersläpningsfaktura – vad säger vi till kunden?",
              body=("Hej,\n\nInnan vi skickar eftersläpningsfakturan på 53 730 kr exkl. moms till Kustbandets "
                    "Färjor – hur formulerar vi oss mot kunden? Mats Lindgren är rak och vill veta varför "
                    "höjningen kommer nu.\n\nSara")),
         dict(from_="Erik Norén <erik.noren@nordvikendigital.se>",
              to="Sara Holm <sara.holm@nordvikendigital.se>; Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-02-12"), subject="SV: KF eftersläpningsfaktura – vad säger vi till kunden?",
              body=("Hej,\n\nVi ska vara raka: prishöjningen följer av indexklausulen i avtalet och skulle "
                    "ha debiterats från november, men vårt interna debiteringsunderlag var felaktigt. Kunden "
                    "har rätt att få veta att det är vårt fel. Föreslår att Sara ringer Mats innan fakturan går ut.\n\nErik")),
         dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Erik Norén <erik.noren@nordvikendigital.se>; Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-02-13"), subject="SV: KF eftersläpningsfaktura – vad säger vi till kunden?",
              body=("Ok, jag ringer Mats i dag och förbereder honom. Fakturan går ut 2026-02-28.\n\nSara"))],
        "E-posttråd: KF-fakturafel – intern avstämning", "2026-02-13", ["EVT-046", "EVT-049"])

    # -- DOC-MAIL-018 SEAB tilläggsförhandling ----------------------------------------------
    mail("DOC-MAIL-018", "mail_2026-01-15_seab_tillaggsforhandling",
        [dict(from_="Björn Sandqvist <bjorn.sandqvist@example.se>",
              to="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2026-01-15"), subject="SE-Billing – tillägg och slutdatum",
              body=("Hej Maja,\n\nSom vi diskuterade behöver SE-Billing ett tilläggsavtal med nytt slutdatum "
                    "2026-07-15 och utökad omfattning. Vi ser gärna att ni återkommer med ett förslag på "
                    "upplägg och pris senast i slutet av januari.\n\nBjörn Sandqvist, Skogsbygdens Energi")),
         dict(from_="Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              to="Björn Sandqvist <bjorn.sandqvist@example.se>",
              date=dt("2026-02-06"), subject="SV: SE-Billing – tillägg och slutdatum",
              body=("Hej Björn,\n\nHärmed bekräftar vi tilläggsavtalet: slutdatum 2026-07-15, utökad "
                    "omfattning +800 000 kr (CTR-2026-004). Signerat av båda parter i dag.\n\nMaja Lindqvist"))],
        "E-posttråd: SE-Billing tilläggsförhandling", "2026-02-06", ["EVT-045"])

    # -- DOC-MAIL-019 klagomålssvar BV ---------------------------------------------------------
    mail("DOC-MAIL-019", "mail_2026-09-12_bv_klagomalssvar",
        [dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Ingrid Holm <ingrid.holm@example.se>",
              date=dt("2026-09-12"), subject="Åtgärdsplan support BV-Journalsystem",
              body=("Hej Ingrid,\n\nSom utlovat kommer här åtgärdsplanen:\n"
                    "1. Namngiven kontaktperson: Sara Holm (tills vidare).\n"
                    "2. Rekrytering av ny supportansvarig pågår (annons ute sedan 2026-09-05).\n"
                    "3. Tillfällig bemanning: två utvecklare avsatta 20 % för support från 2026-09-15.\n"
                    "4. Svarstidsmål: första svar inom 4 arbetstimmar, åtgärd inom 3 arbetsdagar.\n"
                    "5. Månadsvis rapport över svarstider skickas till er fr.o.m. oktober.\n\nMed vänlig hälsning\nSara Holm"))],
        "E-posttråd: Klagomålssvar – åtgärdsplan support BV", "2026-09-12", ["EVT-067"])

    # -- DOC-MAIL-020 offertuppföljning -----------------------------------------------------------
    mail("DOC-MAIL-020", "mail_2026-10-10_offertuppfoljning",
        [dict(from_="Sara Holm <sara.holm@nordvikendigital.se>",
              to="Lisa Sundberg <lisa.sundberg@nordvikendigital.se>",
              date=dt("2026-10-10"), subject="Offertuppföljning vecka 42",
              body=("Hej Lisa,\n\nTre offerter löper ut inom kort – följ upp dessa i veckan:\n"
                    "– OFF-2026-09 till Fjällporten Hotell (giltig t.o.m. 2026-10-20)\n"
                    "– OFF-2026-10 till Skymningsvakten (giltig t.o.m. 2026-10-23)\n"
                    "– OFF-2026-11 till Åskmolns Data (giltig t.o.m. 2026-10-24)\n\nRing kunderna och be om "
                    "besked innan giltighetstiden går ut.\n\nSara"))],
        "E-posttråd: Offertuppföljning (tre offerter löper ut)", "2026-10-10", [])

    # -- DOC-MAIL-021 licensinventering ------------------------------------------------------------
    mail("DOC-MAIL-021", "mail_2026-08-25_licensinventering",
        [dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Jonas Sandberg <jonas.sandberg@nordvikendigital.se>; Maja Lindqvist <maja.lindqvist@nordvikendigital.se>",
              date=dt("2026-08-25"), subject="Licensinventering klar – två verktyg sticker ut",
              body=("Hej,\n\nLicensinventeringen är klar (se DOC-SUP-011). Kortversion: Designsuiten – 9 av 18 "
                    "licenser används (5 600 kr/mån för outnyttjade), Datainsikt – 2 av 10 licenser används "
                    "(6 240 kr/mån för outnyttjade). Tillsammans cirka 142 000 kr/år i onödan.\n\nFöreslår "
                    "att vi säger upp hälften av licenserna vid nästa förnyelsetillfälle.\n\nAnders"))],
        "E-posttråd: Licensinventering – Designsuiten och Datainsikt", "2026-08-25", ["EVT-065"])

    # -- DOC-MAIL-022 pensionsavgift ----------------------------------------------------------------
    mail("DOC-MAIL-022", "mail_2026-01-15_pensionsavgift",
        [dict(from_="Göran Ek <goran.ek@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-01-15"), subject="Pensionspremier 2026 – ny avgiftsnivå",
              body=("Hej Anders,\n\nFrån och med 2026-02-01 gäller en justerad premienivå för er pensionsplan. "
                    "Er månadspremie ökar med cirka 3 %. Nytt premierunderlag bifogas.\n\nGöran Ek, Pensionsvalet"))],
        "E-posttråd: Pensionsvalet – ny avgiftsnivå", "2026-01-15", [])

    # -- DOC-MAIL-023 Talangjakten arkitekt ------------------------------------------------------------
    mail("DOC-MAIL-023", "mail_2026-03-28_talangjakten_arkitekt",
        [dict(from_="Sara Blom <sara.blom@example.se>",
              to="Petra Wahlgren <petra.wahlgren@nordvikendigital.se>",
              date=dt("2026-03-28"), subject="Rekrytering lösningsarkitekt – slutkandidater",
              body=("Hej Petra,\n\nVi har nu tre slutkandidater till arkitektrollen (se matris i DOC-EMP-008). "
                    "Vår rekommendation är kandidat A (Nadia Haddad) med 88 poäng – starkast på "
                    "molnarkitektur och kommunikation. Intervjuomgång 3 med Jonas och Tomas är bokad "
                    "2026-04-08.\n\nSara Blom, Talangjakten"))],
        "E-posttråd: Rekrytering lösningsarkitekt via Talangjakten", "2026-03-28", ["EVT-057"])

    # -- DOC-MAIL-024 Lukas Ek till Dataverket -----------------------------------------------------------
    mail("DOC-MAIL-024", "mail_2026-05-15_lukas_ek_dataverket",
        [dict(from_="Cecilia Nord <cecilia.nord@example.se>",
              to="Jonas Sandberg <jonas.sandberg@nordvikendigital.se>",
              date=dt("2026-05-15"), subject="Lukas Ek – anställning hos Dataverket Nord",
              body=("Hej Jonas,\n\nVi vill bara flagga att Lukas Ek (som vi haft som underkonsultresurs hos er "
                    "via GM-Bergdatasystem) börjar hos oss den 1 juni. Han fortsätter gärna i GM-projektet "
                    "som vår konsult om det fungerar för er.\n\nCecilia Nord, Dataverket Nord")),
         dict(from_="Jonas Sandberg <jonas.sandberg@nordvikendigital.se>",
              to="Cecilia Nord <cecilia.nord@example.se>",
              date=dt("2026-05-16"), subject="SV: Lukas Ek – anställning hos Dataverket Nord",
              body=("Hej Cecilia,\n\nNoterat. Vi återkommer om upplägget för GM-projektet. Observera att "
                    "Daniel Nyström nu blir ensam dataspecialist hos oss – vi vill säkerställa att Lukas "
                    "kan stötta i övergången.\n\nJonas"))],
        "E-posttråd: Lukas Ek går till Dataverket Nord", "2026-05-16", ["EVT-074"])

    # -- DOC-MAIL-025 försäkringsförnyelse ----------------------------------------------------------------
    mail("DOC-MAIL-025", "mail_2026-08-10_forsakring_cyber",
        [dict(from_="Göran Ek <goran.ek@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-08-10"), subject="Försäkringsförnyelse 2027 – tillägg cyber/avbrott",
              body=("Hej Anders,\n\nInför förnyelsen 2027-01-01 vill jag uppmärksamma att er företagsförsäkring "
                    "saknar cyber- och avbrottsförsäkring. Ett tillägg skulle kosta cirka 85 000 kr/år. "
                    "Säg till om ni vill ha en offert.\n\nGöran Ek, Tryggast Försäkring")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Göran Ek <goran.ek@example.se>",
              date=dt("2026-08-12"), subject="SV: Försäkringsförnyelse 2027 – tillägg cyber/avbrott",
              body=("Hej Göran,\n\nTack för påminnelsen. Vi avvaktar tills vidare med tillägget – vi ser över "
                    "kostnadsbilden inför FY27 och återkommer senast i november.\n\nAnders"))],
        "E-posttråd: Försäkringsförnyelse – cybertillägg avvaktas", "2026-08-12", [])

    # -- DOC-MAIL-026 styrelseprotokoll korrigering --------------------------------------------------------
    mail("DOC-MAIL-026", "mail_2026-05-27_styrelseprotokoll_korrigering",
        [dict(from_="Eva Granlund <eva.granlund@example.se>",
              to="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              date=dt("2026-05-27"), subject="Protokollet 7/2026 – felaktig status på SE-Billing",
              body=("Hej Anders,\n\nI utkastet (v0.9) till protokollet från måndagens styrelsemöte står "
                    "SE-Billing som 'Slutlevererad'. Det stämmer inte – projektet är fortfarande pågående "
                    "med slutleverans planerad 2026-07-15. Justera i § 3 innan vi undertecknar.\n\nEva")),
         dict(from_="Anders Bergström <anders.bergstrom@nordvikendigital.se>",
              to="Eva Granlund <eva.granlund@example.se>",
              date=dt("2026-05-27"), subject="SV: Protokollet 7/2026 – felaktig status på SE-Billing",
              body=("Hej Eva,\n\nDu har rätt – jag har blandat ihop statusen med en tidigare prognosrad. "
                    "Justerat till 'Pågående – slutleverans planerad 2026-07-15' i v1.0. Ny version skickas "
                    "för signering i dag.\n\nAnders"))],
        "E-posttråd: Korrigering av styrelseprotokoll 7/2026 (SE-Billing)", "2026-05-27", ["EVT-058"])

    # -- DOC-COM-001 NH klagomålsärende ----------------------------------------------------------------
    d = new_doc()
    head(d, "Klagomålsärende – Norrhamns Hamn AB (NH-Logistikportalen)", "Upprättad 2024-12-18",
         "Sara Holm, Försäljningschef", "DOC-COM-001", "v1.0")
    kv(d, "Kund", "Norrhamns Hamn AB (CUS-011), kontakt Nina Ekström")
    kv(d, "Kategori", "Prestanda – svarstider i godsmottagningen")
    kv(d, "Förekomst", "Tredje gången på samma tema (tidigare: 2024-09-04, 2024-11-06)")
    para(d, "")
    para(d, "Beskrivning: Kunden rapporterar svarstider på 6–8 sekunder i godsmottagningen under eftermiddagarna. Tidigare åtgärder (indexoptimering, cachejustering) har gett tillfällig förbättring men problemet återkommer vid höglast.")
    para(d, "Åtgärdsplan (beslutad):")
    table(d, ["Åtgärd", "Ansvarig", "Klart senast"], [
        ["Prestandatest i kundens produktionsmiljö", "Erik Norén", "2025-01-15"],
        ["Hotfix (frågeoptimering + köhantering)", "Johan Wall", "2025-01-31"],
        ["Månatlig prestandarapport till kunden", "Erik Norén", "Löpande fr.o.m. 2025-02"],
    ])
    save(d, fol / "klagomal_norrhamns_hamn_2024-12-18.docx")
    reg("DOC-COM-001", "correspondence/klagomal_norrhamns_hamn_2024-12-18.docx", "RAPPORT",
        "Klagomålsärende Norrhamns Hamn (NH-Logistikportalen)", "2024-12-18", "P-005",
        ["CUS-011", "P-051", "P-007", "P-015"], event_ids=["EVT-007"])

    # -- DOC-COM-002 BV svarstider ----------------------------------------------------------------
    d = new_doc()
    head(d, "Kunddialog – Blåklintens Vård AB: supportens svarstider", "Upprättad 2026-09-10",
         "Sara Holm, Försäljningschef", "DOC-COM-002", "v1.0")
    kv(d, "Kund", "Blåklintens Vård AB (CUS-007), kontakt Ingrid Holm")
    para(d, "")
    para(d, "Sammanställning av kundens klagomål om svarstider 2026:")
    table(d, ["Datum", "Ärende", "Svarstid (dagar)", "Kommentar"], [
        ["2026-02-19", "Behörighetsfel vid inloggning", "8", "Första klagomålet"],
        ["2026-05-12", "Rapportfel i journalsystemet", "11", "Andra klagomålet"],
        ["2026-09-10", "Blockerad journalhantering", "14", "Tredje klagomålet – eskalering"],
    ])
    para(d, "Orsaker: supportansvarig (Klara Månsson) sade upp sig 2026-08-27; rollen har varit vakant sedan 2026-09-30. Ingen formell ersättare har funnits under perioden.")
    para(d, "Åtgärder: rekrytering av supportansvarig pågår (DOC-EMP-010); tillfällig bemanning med två utvecklare 20 % fr.o.m. 2026-09-15; nytt svarstidsmål 4 arbetstimmar.")
    save(d, fol / "kunddialog_blaklinten_svarstider_2026-09-10.docx")
    reg("DOC-COM-002", "correspondence/kunddialog_blaklinten_svarstider_2026-09-10.docx", "RAPPORT",
        "Kunddialog Blåklintens Vård – svarstider", "2026-09-10", "P-005",
        ["CUS-007", "P-050", "P-030"], event_ids=["EVT-067"])

    # -- DOC-COM-003 förlorad affär Mossbacken -------------------------------------------------------
    d = new_doc()
    head(d, "Förlorad affär – Mossbackens Mekaniska AB", "Upprättad 2026-06-30",
         "Sara Holm, Försäljningschef", "DOC-COM-003", "v1.0")
    kv(d, "Kund", "Mossbackens Mekaniska AB (CUS-008), kontakt Roger Lund")
    kv(d, "Tjänst", "MM-Underhållssystem (löpande räkning 1 030 kr/h)")
    kv(d, "Utfall", "Kunden lämnade oss 2026-06-30 till konkurrent")
    para(d, "")
    para(d, "Orsak: Konkurrenten erbjöd cirka 20 % lägre pris. Vår bedömning var att vi inte kunde möta prisnivån utan negativ marginal.")
    para(d, "Vad vi försökte: prisdiskussion med kunden, paketering av supportavtal samt referenser. Kunden prioriterade pris framför leveranskvalitet.")
    para(d, "Lärdomar: (1) prisa in indexklausuler även i SMB-avtal, (2) följ upp tecken på prispress tidigare i CRM, (3) utvärdera vår kostnadsnivå för underhållsuppdrag.")
    save(d, fol / "forlorad_affar_mossbacken_2026-06-30.docx")
    reg("DOC-COM-003", "correspondence/forlorad_affar_mossbacken_2026-06-30.docx", "RAPPORT",
        "Förlorad affär – Mossbackens Mekaniska", "2026-06-30", "P-005",
        ["CUS-008", "P-053"], event_ids=["EVT-053", "EVT-062"])

    # -- DOC-COM-004 konkurrentbevakning -----------------------------------------------------------
    d = new_doc()
    head(d, "Konkurrentbevakning – notering", "Upprättad 2026-09-30",
         "Lisa Sundberg, Marknadsansvarig", "DOC-COM-004", "v1.0")
    table(d, ["Konkurrent", "Observation", "Konsekvens"], [
        ["Blå Ocean IT AB", "Aggressiv prissättning mot våra SMB-kunder (Mossbacken förlorad 2026-06)", "Prispress i SMB-segmentet"],
        ["Dataverket Nord AB", "Rekryterade vår dataanalytiker Lukas Ek (2026-06); kan bli konkurrent inom data/AI", "Nyckelpersonsrisk + konkurrens inom data"],
        ["Större konsultbolag", "Offentliga ramavtal pressas ned i pris", "Offentliga affärer kräver referenser"],
    ])
    para(d, "Rekommendation: Bevaka Blå Oceans prissättning kvartalsvis; överväg partnerdialog med Dataverket Nord för att behålla GM-relationen.")
    save(d, fol / "konkurrentbevakning_2026-09-30.docx")
    reg("DOC-COM-004", "correspondence/konkurrentbevakning_2026-09-30.docx", "RAPPORT",
        "Konkurrentbevakning – notering", "2026-09-30", "P-006",
        ["ORG-NORDVIKEN", "SUP-035", "CUS-008"])


# ---------------------------------------------------------------------------
# projects/
# ---------------------------------------------------------------------------

def section_projects(m: Model) -> None:
    fol = F["projects"]

    def status(doc_id, fname, title, datum, author, kund, rows, sections, evt=None, note=""):
        d = new_doc()
        head(d, title, datum, author, doc_id)
        kv(d, "Kund", kund)
        table(d, ["Fält", "Värde"], rows)
        for rub, txt in sections:
            para(d, rub, bold=True)
            for line in txt:
                para(d, line)
        save(d, fol / fname)
        reg(doc_id, f"projects/{fname}", "RAPPORT", title, datum, author,
            ["ORG-NORDVIKEN"], event_ids=evt or [], note=note)

    # -- SE-Billing statusrapporter --------------------------------------------
    status("DOC-PRJ-001", "se_billing_status_2025-10-31.docx",
           "Projektstatusrapport – SE-Billing", "2025-10-31", "David Ekström, projektledare",
           "Skogsbygdens Energi AB (PRJ-001)",
           [["Status", "GUL – försenad"], ["Planerad slutleverans", "2026-02-28 (ursprunglig plan)"],
            ["Prognos slutleverans", "2026-04-30"], ["Ackumulerad försening", "cirka 8 veckor"],
            ["Budget", "9 400 000 kr fast pris"], ["Upparbetat", "5 800 000 kr"]],
           [("Orsaker till försening", ["Underkonsulter (Kraftkod) kom in senare än planerat; omfattningsändringar i rapportmodulen."]),
            ("Åtgärder", ["Återhämtningsplan framtagen; extra resurser fr.o.m. november."]),
            ("Risker", ["Fortsatta omfattningsändringar, nyckelpersonsberoende till Tomas Berg."])],
           note="Försening ca 8 veckor vid 2025-10-31.")

    status("DOC-PRJ-002", "se_billing_status_2026-02-10.docx",
           "Projektstatusrapport – SE-Billing", "2026-02-10", "David Ekström, projektledare",
           "Skogsbygdens Energi AB (PRJ-001)",
           [["Status", "GUL – försenad"], ["Planerad slutleverans", "2026-07-15 (tilläggsavtal)"],
            ["Prognos slutleverans", "2026-07-15"], ["Ackumulerad försening", "cirka 12 veckor"],
            ["Budget", "9 400 000 kr + tillägg 800 000 kr (CTR-2026-004)"]],
           [("Tilläggsavtal", ["Tilläggsavtal signerat 2026-02-06: nytt slutdatum 2026-07-15, +800 000 kr."]),
            ("Resurser", ["Kraftkod Konsult (2 utvecklare) kvar till slutleverans."]),
            ("Risker", ["Acceptanstestets omfattning; beroende av SEAB:s testmiljö."])],
           evt=["EVT-045"], note="Tilläggsavtal CTR-2026-004 signerat 2026-02-06.")

    status("DOC-PRJ-003", "se_billing_status_2026-05-15.docx",
           "Projektstatusrapport – SE-Billing", "2026-05-15", "David Ekström, projektledare",
           "Skogsbygdens Energi AB (PRJ-001)",
           [["Status", "GUL – försenad"], ["Planerad slutleverans", "2026-07-15"],
            ["Ackumulerad försening", "cirka 14 veckor"],
            ["Budget", "10 200 000 kr inkl. tillägg"]],
           [("Lägesbild", ["All utveckling klar; acceptanstest pågår. Två kritiska fel återstår."]),
            ("Risker", ["Kundens testresurser är begränsade i juni; risk att slutleveransen glider till augusti."])],
           note="Försening ca 14 veckor.")

    status("DOC-PRJ-004", "se_billing_status_2026-07-10.docx",
           "Projektstatusrapport – SE-Billing (inför slutleverans)", "2026-07-10", "David Ekström, projektledare",
           "Skogsbygdens Energi AB (PRJ-001)",
           [["Status", "GRÖN – slutleverans 2026-07-15"], ["Slutleverans", "2026-07-15"],
            ["Acceptanstest", "Godkänt 2026-07-09"], ["Slutmilstolpe", "800 000 kr faktureras vid godkänd slutleverans"]],
           [("Återstående", ["Överlämning av dokumentation, utbildning av SEAB:s driftteam."]),
            ("Notering", ["Projektet avslutas formellt 2026-07-15 med slutrapport (DOC-PRJ-030)."])],
           note="Inför slutleverans 2026-07-15.")

    d = new_doc()
    head(d, "Slutrapport – SE-Billing (ny faktureringsplattform)", "2026-07-15",
         "David Ekström, projektledare", "DOC-PRJ-030", "v1.0")
    kv(d, "Kund", "Skogsbygdens Energi AB (PRJ-001, CTR-2023-002 + CTR-2026-004)")
    table(d, ["Fält", "Värde"], [
        ["Projektperiod", "2024-10-01 – 2026-07-15"],
        ["Ekonomi", "Fast pris 9 400 000 kr + tillägg 800 000 kr = 10 200 000 kr"],
        ["Slutleverans", "2026-07-15 – godkänd av kunden"],
        ["Total försening", "cirka 15 veckor mot ursprunglig plan"],
        ["Underkonsulter", "Kraftkod Konsult AB (2 utvecklare)"],
    ])
    para(d, "Sammanfattning")
    para(d, "SE-Billing slutlevererades och godkändes 2026-07-15. Förseningen förklaras främst av omfattningsändringar och senare tillskott av underkonsulter. Slutmilstolpen om 800 000 kr faktureras i juli.")
    para(d, "Lärdomar: (1) fastprisprojekt med omfattningsändringar kräver formell change management från start, (2) underkonsulter behöver onboardingplan, (3) kundens acceptanstest bör resursplaneras tidigt.")
    save(d, fol / "se_billing_slutrapport_2026-07-15.docx")
    reg("DOC-PRJ-030", "projects/se_billing_slutrapport_2026-07-15.docx", "RAPPORT",
        "Slutrapport SE-Billing", "2026-07-15", "P-008",
        ["PRJ-001", "CUS-001", "SUP-034"], event_ids=["EVT-063"],
        note="Slutlevererad och godkänd 2026-07-15; slutmilestone 800 000 kr faktureras.")

    # -- TS-Produktionsportal --------------------------------------------------
    status("DOC-PRJ-005", "ts_produktionsportal_status_2026-02-28.docx",
           "Projektstatusrapport – TS-Produktionsportal", "2026-02-28", "Karin Olsson, projektledare",
           "Timmervikens Såg AB (PRJ-009)",
           [["Status", "GUL – försenad"], ["Planerad slutleverans", "2026-03-31"],
            ["Prognos slutleverans", "2026-05-31"], ["Försening", "cirka 4 veckor ackumulerat"],
            ["Budget", "1 800 000 kr fast pris"], ["Viteklausul", "1 %/vecka, tak 10 %"]],
           [("Orsaker", ["Integrationen mot kundens produktionssystem tog längre tid än estimerat."]),
            ("Risker", ["Ytterligare försening kan utlösa vite; kunden avvaktar med acceptans."])],
           note="Fast pris 1,8 MSEK; viteklausul 1 %/vecka, tak 10 %.")

    status("DOC-PRJ-006", "ts_produktionsportal_status_2026-05-15.docx",
           "Projektstatusrapport – TS-Produktionsportal", "2026-05-15", "Karin Olsson, projektledare",
           "Timmervikens Såg AB (PRJ-009)",
           [["Status", "RÖD – försenad"], ["Planerad slutleverans", "2026-03-31"],
            ["Prognos slutleverans", "2026-05-31"], ["Försening", "8 veckor"],
            ["Vite", "Avtalsenligt vite 8 % (144 000 kr), tak 10 %"]],
           [("Viteförhandling", ["Förhandling pågår med kunden om nedsättning av vitet mot snabb slutacceptans."]),
            ("Beslutspunkt", ["Förlikningsförslag: kreditnota 90 000 kr (50 % av vitet) mot slutacceptans – bereds med CFO."])],
           note="8 veckor försenad; viteförhandling pågår.")

    # -- SU-Produktionssystem -----------------------------------------------------
    status("DOC-PRJ-007", "su_produktionssystem_status_2026-06-30.docx",
           "Projektstatusrapport – SU-Produktionssystem", "2026-06-30", "Karin Olsson, projektledare",
           "Sundbygdens Varv AB (PRJ-029)",
           [["Status", "GRÖN"], ["Planerad slutleverans", "2026-11-30"],
            ["Budget", "1 950 000 kr fast pris (CTR-2026-001)"],
            ["Fakturerat t.o.m. juni", "1 300 000 kr"],
            ["Viteklausul", "1 %/vecka, tak 10 %; källkodsdepå hos tredje part krävs"]],
           [("Notering", ["Projektet övertogs av Karin Olsson efter Magnus Ryds avgång 2026-03-31."]),
            ("Risker", ["Källkodsdepån ännu inte upprättad hos tredje part – måste vara på plats före driftsättning."])],
           note="Fast pris 1,95 MSEK; fakturerat 1,3 MSEK per 2026-06.")

    status("DOC-PRJ-008", "su_produktionssystem_status_2026-09-30.docx",
           "Projektstatusrapport – SU-Produktionssystem", "2026-09-30", "Karin Olsson, projektledare",
           "Sundbygdens Varv AB (PRJ-029)",
           [["Status", "GUL"], ["Planerad slutleverans", "2026-11-30"],
            ["Budget", "1 950 000 kr fast pris"], ["Fakturerat t.o.m. september", "1 600 000 kr"],
            ["Återstår att fakturera", "350 000 kr (plan november 2026)"]],
           [("Lägesbild", ["Utvecklingen klar till 90 %; kundens driftsättningsmiljö försenad med två veckor."]),
            ("Risker", ["Vite vid försening (1 %/vecka, tak 10 %). Källkodsdepå: avtal med depåhållare klart, deponering sker 2026-10-15."])],
           note="Fakturerat 1,6 MSEK; 350 kkr återstår (plan 2026-11).")

    # -- GV-Digitalisering ----------------------------------------------------------
    status("DOC-PRJ-009", "gv_digitalisering_status_2026-03-31.docx",
           "Projektstatusrapport – GV-Digitalisering", "2026-03-31", "Karin Olsson, projektledare",
           "Gråvikens kommun (PRJ-004)",
           [["Status", "GRÖN"], ["Avtalsform", "Löpande räkning 1 050 kr/h (ramavtal CTR-2022-007)"],
            ["Volym", "cirka 80–150 timmar/månad"]],
           [("Notering", ["Ramavtalet innehåller KPI-indexklausul; prisjusteringar hanteras i samband med faktureringsöversynen."]),
            ("Lägesbild", ["Digitalisering av tre förvaltningsprocesser pågår; leverans enligt plan."])],
           note="Ramavtal med indexklausul (bas 2023-10, uppräkning per 2025-10-01).")

    # -- Projektmötesprotokoll ×5 ----------------------------------------------------
    def pmote(doc_id, fname, title, datum, projekt, deltagare, punkter):
        d = new_doc()
        head(d, title, datum, "Projektledare", doc_id)
        kv(d, "Projekt", projekt)
        kv(d, "Deltagare", deltagare)
        para(d, "")
        for i, (rub, txt) in enumerate(punkter, 1):
            para(d, f"{i}. {rub}", bold=True)
            para(d, txt)
        save(d, fol / fname)
        reg(doc_id, f"projects/{fname}", "PROTOKOLL", title, datum, "P-008",
            ["ORG-NORDVIKEN"], note="")

    pmote("DOC-PRJ-010", "projektmote_se_billing_2026-02-20.docx",
          "Projektmötesprotokoll – SE-Billing", "2026-02-20", "SE-Billing (PRJ-001)",
          "David Ekström, Tomas Berg, Fredrik Lund, Kraftkod (Stefan Kraft), Björn Sandqvist (SEAB)",
          [("Status", "Utveckling klar till 85 %. Återstår rapportmodulen och prestandatester."),
           ("Hinder", "Väntar på kundgodkännande av gränssnitt för rapportmodulen sedan 2026-02-06 (SEAB att återkomma)."),
           ("Beslut", "Prestandatest bokas när kundgodkännandet finns. Tomas tar fram testdata.")])

    pmote("DOC-PRJ-011", "projektmote_ts_2026-04-10.docx",
          "Projektmötesprotokoll – TS-Produktionsportal", "2026-04-10", "TS-Produktionsportal (PRJ-009)",
          "Karin Olsson, Emma Persson, Viktor Lind, Ola Persson (Timmervikens Såg)",
          [("Status", "Integration mot produktionssystemet testas. Förseningen nu 6 veckor."),
           ("Hinder", "Kompetensbrist: endast en utvecklare kan kundens produktionssystem – ingen backup finns."),
           ("Beslut", "Viktor Lind går bredvid för kunskapsöverföring fr.o.m. nästa vecka.")])

    pmote("DOC-PRJ-012", "projektmote_su_2026-06-05.docx",
          "Projektmötesprotokoll – SU-Produktionssystem", "2026-06-05", "SU-Produktionssystem (PRJ-029)",
          "Karin Olsson, Oskar Nilsson, Camilla Westin, Sundbygdens Varv (driftchef)",
          [("Status", "Milestone 2 levererad. Källkodsdepåfrågan diskuterad."),
           ("Hinder", "Integrationer går sönder: testmiljöintegrationen mot varvets system har fallit två gånger den senaste veckan."),
           ("Beslut", "Källkodsdepå hos tredje part ska vara på plats före driftsättning (avtalskrav).")])

    pmote("DOC-PRJ-013", "projektmote_su_2026-08-14.docx",
          "Projektmötesprotokoll – SU-Produktionssystem", "2026-08-14", "SU-Produktionssystem (PRJ-029)",
          "Karin Olsson, Oskar Nilsson, Simon Dahl, Sundbygdens Varv (driftchef)",
          [("Status", "Utveckling 85 % klar. Driftsättningsmiljön hos kunden försenad."),
           ("Hinder", "Väntar på kundgodkännande av säkerhetsgranskningen sedan 2026-08-01."),
           ("Beslut", "Simon Dahl dokumenterar driftsättningsrutinen; risk för vite flaggas till Erik Norén.")])

    pmote("DOC-PRJ-014", "projektmote_se_forvaltning_2026-09-04.docx",
          "Projektmötesprotokoll – SE-Förvaltning", "2026-09-04", "SE-Förvaltning (PRJ-003)",
          "David Ekström, Johan Wall, Björn Sandqvist (SEAB)",
          [("Status", "Förvaltningsläget stabilt efter SE-Billing-överlämningen. Tre incidenter i augusti, alla lösta inom SLA."),
           ("Hinder", "Integrationer går sönder: faktureringsintegrationen har felat två gånger sedan juli."),
           ("Beslut", "Johan Wall tar fram förslag på stabilisering till nästa möte 2026-10-02.")])


from datetime import date



def _fy26_hours(m: Model, sch_id: str) -> float:
    s = m.schedule(sch_id)
    tot = 0.0
    for k, v in s.monthly_hours.items():
        y, mo = int(k[:4]), int(k[5:7])
        if (2025, 10) <= (y, mo) <= (2026, 9):
            tot += float(v)
    return tot


# ---------------------------------------------------------------------------
# employees/
# ---------------------------------------------------------------------------

def section_employees(m: Model) -> None:
    fol = F["employees"]

    def hr_doc(doc_id, fname, title, datum, author, blocks, evt=None, note="", version="1.0"):
        d = new_doc()
        head(d, title, datum, author, doc_id, version)
        for block in blocks:
            kind = block[0]
            if kind == "p":
                para(d, block[1])
            elif kind == "b":
                para(d, block[1], bold=True)
            elif kind == "t":
                table(d, block[1], block[2])
            elif kind == "kv":
                if len(block) == 3:
                    kv(d, block[1], block[2])
                else:
                    kv(d, block[1][0], block[1][1])
        save(d, fol / fname)
        reg(doc_id, f"employees/{fname}", "RAPPORT", title, datum, author,
            ["ORG-NORDVIKEN"], event_ids=evt or [], note=note, version=version)

    # ---- DOC-HR-001 Gustav Pettersson -------------------------------------
    hr_doc("DOC-HR-001", "hr_2024-11-15_gustav_pettersson_avslutssamtal.docx",
           "Avslutssamtal – Gustav Pettersson", "2024-11-15", "P-004",
           [("kv", ("Medarbetare", "Gustav Pettersson (EMP-032), senior utvecklare")),
            ("kv", ("Sista arbetsdag", "2024-11-15")),
            ("p", "Gustav har sagt upp sig på eget initiativ och börjar hos konkurrenten Blå Ocean IT AB."),
            ("p", "I anställningsavtalet finns en konkurrensklausul om 12 månader. Frågan om klausulens giltighet har överlämnats till Advokatfirman Krav & Klar (se DOC-MAIL-001)."),
            ("b", "Åtgärder"),
            ("t", ["Åtgärd", "Ansvarig", "Status"], [
                ["Rättslig bedömning av konkurrensklausulen", "Maja Lindqvist", "Pågående"],
                ["Överlämning av pågående uppdrag (SE-Billing)", "Erik Norén", "Klart"],
                ["Återlämning av utrustning och behörigheter", "Jonas Sandberg", "Klart"],
            ]),
            ("p", "Skäl till avgång: bättre ersättning och större ansvar hos konkurrenten.")],
           evt=["EVT-004"])

    # ---- DOC-HR-002 Martina Bergqvist --------------------------------------
    hr_doc("DOC-HR-002", "hr_2025-01-31_martina_bergqvist_avslutssamtal.docx",
           "Avslutssamtal – Martina Bergqvist", "2025-01-31", "P-004",
           [("kv", ("Medarbetare", "Martina Bergqvist (EMP-033), projektledare")),
            ("kv", ("Sista arbetsdag", "2025-01-31")),
            ("p", "Martina flyttar till Göteborg och har fått ny tjänst där. Hon har lett KL-Vårdportal och delar av GV-Digitalisering."),
            ("b", "Åtgärder"),
            ("t", ["Åtgärd", "Ansvarig", "Status"], [
                ["Överlämning KL-Vårdportal till Karin Olsson", "Erik Norén", "Klart"],
                ["Rekrytering av projektledare (ersättare)", "Petra Wahlgren", "Klart 2025-03"],
            ])],
           evt=["EVT-011"])

    # ---- DOC-HR-003 Tobias Lindqvist ----------------------------------------
    hr_doc("DOC-HR-003", "hr_2025-03-14_tobias_lindqvist_avsked.docx",
           "Avsked – Tobias Lindqvist (underlag)", "2025-03-14", "P-004",
           [("kv", ("Medarbetare", "Tobias Lindqvist (EMP-034), utvecklare")),
            ("kv", ("Beslut", "Avsked 2025-03-14 p.g.a. bristande prestation")),
            ("p", "Bakgrund: upprepade uppföljningssamtal 2024-09-24, 2024-11-18 och 2025-02-10 med dokumenterade brister i leveranser och kodkvalitet. Handlingsplan från 2024-11-18 har inte följts."),
            ("p", "Medarbetaren bestrider uppsägningen via facket. Ärendet har överlämnats till Advokatfirman Krav & Klar för förhandling."),
            ("b", "Bilagor"),
            ("p", "1. Uppföljningssamtal 2024-09-24. 2. Handlingsplan 2024-11-18. 3. Uppföljning 2025-02-10.")],
           evt=["EVT-016"])

    # ---- DOC-HR-004 Lönerevision 2025 ----------------------------------------
    hr_doc("DOC-HR-004", "hr_2025-04-03_lonerevision_2025.docx",
           "Lönerevision 2025 – beslut", "2025-04-03", "P-004",
           [("p", "Årlig lönerevision genomförd. Åtta medarbetare får lönehöjningar fr.o.m. 2025-04-01 enligt nedan. Höjningarna grundas på utvärderingssamtal, marknadsläget och individuell prestation."),
            ("t", ["Medarbetare", "Höjning", "Motivering"], [
                ["Fredrik Lund", "3,0 %", "Nyckelkompetens SE-Billing"],
                ["Emma Persson", "3,2 %", "Stark leverans TS-uppdrag"],
                ["Johan Wall", "2,8 %", "Ersätter senior i SE-Integration"],
                ["Oskar Nilsson", "3,5 %", "Marknadsjustering"],
                ["Viktor Lind", "2,5 %", "Utveckling enligt plan"],
                ["Elin Andersson", "2,5 %", "Utveckling enligt plan"],
                ["Patrik Öberg", "3,0 %", "DevOps-kompetens"],
                ["Maria Gustavsson", "2,8 %", "Testledning PF och SU"],
            ])],
           evt=["EVT-019"])

    # ---- DOC-HR-005 Jenny Lindholm -------------------------------------------
    hr_doc("DOC-HR-005", "hr_2025-06-30_jenny_lindholm_avslutssamtal.docx",
           "Avslutssamtal – Jenny Lindholm", "2025-06-30", "P-004",
           [("kv", ("Medarbetare", "Jenny Lindholm (EMP-035), testare")),
            ("kv", ("Sista arbetsdag", "2025-06-30")),
            ("p", "Jenny lämnar för en ny roll i en annan bransch (offentlig verksamhet). Hon har stöttat TS-Produktionsportal och PF-Kundportal."),
            ("p", "Överlämning av testfall till Maria Gustavsson genomförd. Inga ouppklarade ärenden.")],
           evt=["EVT-023"])

    # ---- DOC-HR-006 Förlikning Tobias ------------------------------------------
    hr_doc("DOC-HR-006", "hr_2025-08-27_forlikning_tobias_lindqvist.docx",
           "Förlikningsavtal – Tobias Lindqvist", "2025-08-27", "P-004",
           [("p", "Förlikning träffad mellan Nordviken Digital AB och Tobias Lindqvist i tvisten om avskedet 2025-03-14."),
            ("kv", ("Avgångsvederlag", "3 månadslöner = 141 000 kr")),
            ("kv", ("Advokatkostnader", "Betalas av bolaget")),
            ("kv", ("Utbetalning", "2025-09-05 via lönekörningen")),
            ("p", "Parterna medger inga fel men är överens om att avsluta tvisten. Ömsesidig sekretess om förlikningen."),
            ("p", "Tvisten är därmed slutligt reglerad.")],
           evt=["EVT-027"])

    # ---- DOC-HR-007 Rasmus Holm ------------------------------------------------
    hr_doc("DOC-HR-007", "hr_2025-10-31_rasmus_holm_avslutssamtal.docx",
           "Avslutssamtal – Rasmus Holm", "2025-10-31", "P-004",
           [("kv", ("Medarbetare", "Rasmus Holm (EMP-036), senior utvecklare")),
            ("kv", ("Sista arbetsdag", "2025-10-31")),
            ("p", "Rasmus har rekryterats av kunden Skogsbygdens Energi AB (SEAB) och börjar där 2025-11-01."),
            ("b", "Intressekonflikt"),
            ("p", "Intressekonflikt och eventuell konkurrensklausul har diskuterats i ledningsgruppen (DOC-MGMT-006). Rättslig bedömning inhämtas från Krav & Klar. Överlämningen av SE-Integration till Johan Wall är genomförd.")],
           evt=["EVT-034"])

    # ---- DOC-HR-008 Anna Westberg ------------------------------------------------
    hr_doc("DOC-HR-008", "hr_2026-02-28_anna_westberg_avslutssamtal.docx",
           "Avslutssamtal – Anna Westberg", "2026-02-28", "P-004",
           [("kv", ("Medarbetare", "Anna Westberg (EMP-037), marknadskoordinator")),
            ("kv", ("Sista arbetsdag", "2026-02-28")),
            ("p", "Anna uppger arbetsbelastning som huvudskäl till avgången: marknadsarbetet har växt utan att resurserna följt med, och hon har under lång tid burit flera roller."),
            ("b", "Åtgärder"),
            ("t", ["Åtgärd", "Ansvarig", "Status"], [
                ["Se över arbetsbelastningen i staben", "Petra Wahlgren", "Pågående"],
                ["Rekrytering av marknadskoordinator", "Petra Wahlgren", "Ej startad (pausad i kostnadsprogrammet)"],
            ]),
            ("p", "Notering: avslutssamtalet förstärker signalerna i medarbetarundersökningen 2025 om arbetsbelastning.")],
           evt=["EVT-048"])

    # ---- DOC-HR-009 Lönerevision 2026 ----------------------------------------------
    hr_doc("DOC-HR-009", "hr_2026-04-01_lonerevision_2026.docx",
           "Lönerevision 2026 – beslut", "2026-04-01", "P-004",
           [("p", "Årlig lönerevision genomförd. Tolv medarbetare får lönehöjningar fr.o.m. 2026-04-01. Höjningarna grundas på utvärderingssamtal, kompetensförsörjningsbehov (särskilt DevOps, data/AI och arkitektur) samt marknadsläget."),
            ("t", ["Medarbetare", "Höjning", "Motivering"], [
                ["David Ekström", "3,0 %", "SE-Billing och produktutveckling"],
                ["Karin Olsson", "3,0 %", "Övertagit SU-projektet"],
                ["Tomas Berg", "3,5 %", "Arkitekturkompetens"],
                ["Fredrik Lund", "2,8 %", "Leverans SE-Integration"],
                ["Emma Persson", "3,0 %", "TS och SU"],
                ["Oskar Nilsson", "3,0 %", "SU-leverans"],
                ["Camilla Westin", "2,5 %", "Utveckling enligt plan"],
                ["Viktor Lind", "2,5 %", "Utveckling enligt plan"],
                ["Elin Andersson", "2,5 %", "Utveckling enligt plan"],
                ["Maria Gustavsson", "3,0 %", "Testledning, nyckelkompetens"],
                ["Daniel Nyström", "3,5 %", "Data/AI, nyckelkompetens"],
                ["Patrik Öberg", "3,0 %", "DevOps"],
            ])],
           evt=["EVT-055"])

    # ---- DOC-HR-010 Robin Åkerlund ---------------------------------------------------
    hr_doc("DOC-HR-010", "hr_2026-01-31_robin_akerlund_provanstallning.docx",
           "Beslut – provanställning avslutas utan övergång", "2026-01-31", "P-004",
           [("kv", ("Medarbetare", "Robin Åkerlund (EMP-021), utvecklare")),
            ("kv", ("Beslut", "Provanställningen avslutas 2026-01-31; ingen övergång till tillsvidareanställning")),
            ("p", "Bedömningsunderlag: leveranshastighet och självständighet har inte nått förväntad nivå under provanställningen trots handledning (handledare Johan Wall)."),
            ("p", "Beslutet fattades efter avstämning med handledare och leveranschef 2026-01-28.")],
           evt=["EVT-071"])

    # ---- DOC-HR-011 Magnus Ryd -----------------------------------------------------------
    hr_doc("DOC-HR-011", "hr_2026-02-27_magnus_ryd_avslutssamtal.docx",
           "Avslutssamtal – Magnus Ryd", "2026-02-27", "P-004",
           [("kv", ("Medarbetare", "Magnus Ryd (EMP-010), projektledare")),
            ("kv", ("Uppsägning", "2026-02-27, 3 månaders uppsägningstid")),
            ("kv", ("Sista arbetsdag", "2026-03-31")),
            ("p", "Magnus uppger utmattningsrelaterade skäl till uppsägningen: långvarig hög belastning i SU-Produktionssystem och svårighet att återhämta sig."),
            ("b", "Åtgärder"),
            ("t", ["Åtgärd", "Ansvarig", "Status"], [
                ["Övertagande av SU-projektet", "Karin Olsson", "Klart"],
                ["Se över belastningen i leveransteamet", "Erik Norén", "Pågående"],
                ["Företagshälsovårdsstöd erbjudet", "Petra Wahlgren", "Klart"],
            ]),
            ("p", "Notering: förstärker signalerna i medarbetarundersökningen 2025 om arbetsbelastning.")],
           evt=["EVT-072"])

    # ---- DOC-HR-012 Sofia Lindgren ---------------------------------------------------------
    hr_doc("DOC-HR-012", "hr_2026-04-29_sofia_lindgren_avslutssamtal.docx",
           "Avslutssamtal – Sofia Lindgren", "2026-04-29", "P-004",
           [("kv", ("Medarbetare", "Sofia Lindgren (EMP-016), senior utvecklare")),
            ("kv", ("Uppsägning", "2026-04-29, 2 månaders uppsägningstid")),
            ("kv", ("Sista arbetsdag", "2026-06-30")),
            ("p", "Sofia har fått tjänst hos kunden Polstjärnan Försäkring AB och börjar där 2026-07-01."),
            ("p", "Intressekonflikt noterad: Sofia har arbetat i PF-Kundportal hos Polstjärnan som konsult. Överlämning till Emma Persson planerad före avgång.")],
           evt=["EVT-073"])

    # ---- DOC-HR-013 Lukas Ek ----------------------------------------------------------------
    hr_doc("DOC-HR-013", "hr_2026-05-31_lukas_ek_avslutssamtal.docx",
           "Avslutssamtal – Lukas Ek", "2026-05-31", "P-004",
           [("kv", ("Medarbetare", "Lukas Ek (EMP-031), dataanalytiker")),
            ("kv", ("Sista arbetsdag", "2026-05-31")),
            ("p", "Lukas har rekryterats av underkonsulten Dataverket Nord AB och börjar där 2026-06-01."),
            ("b", "Konsekvens"),
            ("p", "Daniel Nyström blir därefter ensam dataspecialist i bolaget (nyckelpersonsrisk, se DOC-RISK-001 R-02). Lukas fortsätter i GM-Bergdatasystem som konsult från Dataverket under en övergångsperiod.")],
           evt=["EVT-074"])

    # ---- DOC-HR-014 Björn Falk ----------------------------------------------------------------
    hr_doc("DOC-HR-014", "hr_2026-07-01_bjorn_falk_avslutssamtal.docx",
           "Avslutssamtal – Björn Falk", "2026-07-01", "P-004",
           [("kv", ("Medarbetare", "Björn Falk (EMP-029), utvecklare")),
            ("kv", ("Uppsägning", "2026-07-01, 2 månaders uppsägningstid")),
            ("kv", ("Sista arbetsdag", "2026-08-31")),
            ("p", "Björn flyttar utomlands av familjeskäl. Han har arbetat i SE-Förvaltning och NH-Förvaltning."),
            ("p", "Överlämning till Johan Wall och Hugo Larsson genomförd i augusti.")],
           evt=["EVT-075"])

    # ---- DOC-HR-015 Klara Månsson ----------------------------------------------------------------
    hr_doc("DOC-HR-015", "hr_2026-08-27_klara_mansson_avslutssamtal.docx",
           "Avslutssamtal – Klara Månsson", "2026-08-27", "P-004",
           [("kv", ("Medarbetare", "Klara Månsson (EMP-030), supportansvarig")),
            ("kv", ("Uppsägning", "2026-08-27, 1 månads uppsägningstid")),
            ("kv", ("Sista arbetsdag", "2026-09-30")),
            ("p", "Klara har fått en ny tjänst med kortare uppsägningstid enligt avtal. Hon har ensam ansvarat för supporten sedan 2022."),
            ("b", "Bemanningsgap"),
            ("p", "Supporten står därefter utan ansvarig. Rekrytering av supportansvarig pågår (DOC-EMP-010). Tillfällig bemanning: två utvecklare 20 % fr.o.m. 2026-09-15.")],
           evt=["EVT-076"])

    # ---- DOC-EMP-001 Medarbetarundersökning 2025 -----------------------------------------------
    hr_doc("DOC-EMP-001", "medarbetarundersokning_2025.docx",
           "Medarbetarundersökning 2025 – resultat och åtgärder", "2025-11-14", "P-004",
           [("kv", ("Svarsfrekvens", "84 % (26 av 31 medarbetare)")),
            ("kv", ("eNPS", "18")),
            ("p", "Huvudteman i fritextsvaren: (1) arbetsbelastningen i leveransteamet, (2) otydliga karriärvägar, (3) verktygs- och systemfrustration, (4) önskemål om mer feedback från chefer."),
            ("b", "Åtgärdslista (beslutad av ledningsgruppen 2025-12-01)"),
            ("t", ["Åtgärd", "Ägare", "Klart senast", "Status 2026-10"], [
                ["Övertidsöversyn och beläggningsmål per team", "Erik Norén", "2026-03-31", "Öppen"],
                ["Karriärramverk med två spår (specialist/ledare)", "Petra Wahlgren", "2026-06-30", "Öppen"],
                ["Förbättra utvecklingsverktygen (CI/CD, testmiljöer)", "Jonas Sandberg", "2026-02-28", "Genomförd"],
                ["Ledarskapsutbildning för projektledare", "Petra Wahlgren", "2026-05-31", "Öppen"],
                ["Friskvårdsbidrag 4 000 kr/år infört", "Petra Wahlgren", "2026-01-01", "Genomförd"],
            ])],
           note="Tre åtgärder fortfarande öppna i oktober 2026.")

    # ---- DOC-EMP-002 Medarbetarundersökning 2026 -----------------------------------------------
    hr_doc("DOC-EMP-002", "medarbetarundersokning_2026.docx",
           "Medarbetarundersökning 2026 – preliminärt resultat", "2026-09-18", "P-004",
           [("kv", ("Svarsfrekvens", "68 % (16 av 24 medarbetare)")),
            ("kv", ("eNPS", "11")),
            ("p", "Preliminära resultat (slutrapport kommer 2026-10-30):"),
            ("t", ["Tema", "Utfall 2026", "Utfall 2025"], [
                ["Arbetsbelastning", "3,1 / 5 (sämst betyg, leveransteamet 2,7)", "3,3 / 5"],
                ["Ledarskap", "3,4 / 5", "3,6 / 5"],
                ["Verktyg och system", "3,8 / 5", "3,2 / 5"],
                ["Trygghet och trivsel", "4,0 / 5", "4,1 / 5"],
            ]),
            ("b", "Ledarskapsfeedback (återkommande teman)"),
            ("p", "– Önskemål om tydligare prioriteringar när flera projekt konkurrerar."),
            ("p", "– Önskemål om mer återkoppling på utfört arbete."),
            ("p", "– Upplevelse av att beslut som rör teamen fattas utan delaktighet."),
            ("p", "Leveransteamet rapporterar hög belastning i samband med SE-Billing-överlämningen och supportvakansen.")],
           note="Svarsfrekvens lägre än 2025 (68 %).")

    # ---- DOC-EMP-003 Utvecklingssamtalsregister ------------------------------------------------
    rows = [
        ["Maja Lindqvist", "VD", "2026-05-20", "2026-11-15"],
        ["Jonas Sandberg", "CTO", "2026-04-10", "2026-10-20"],
        ["Anders Bergström", "CFO", "2026-03-25", "2026-09-30"],
        ["Petra Wahlgren", "HR- och kontorschef", "2026-02-12", "2026-09-15"],
        ["Sara Holm", "Försäljningschef", "2026-04-08", "2026-10-25"],
        ["Lisa Sundberg", "Marknadsansvarig", "2026-01-22", "2026-08-30"],
        ["Erik Norén", "Leveranschef", "2026-03-14", "2026-09-28"],
        ["David Ekström", "Projektledare", "2026-02-19", "2026-09-12"],
        ["Karin Olsson", "Projektledare", "2026-05-06", "2026-11-10"],
        ["Tomas Berg", "Lösningsarkitekt", "2025-09-11", "Ej planerat"],
        ["Nadia Haddad", "Lösningsarkitekt", "2026-09-02", "2027-03-01"],
        ["Fredrik Lund", "Senior utvecklare", "2024-11-20", "Ej planerat"],
        ["Emma Persson", "Senior utvecklare", "2025-01-15", "2026-11-05"],
        ["Johan Wall", "Senior utvecklare", "2024-12-05", "Ej planerat"],
        ["Oskar Nilsson", "Senior utvecklare", "2025-03-06", "2026-10-15"],
        ["Camilla Westin", "Senior utvecklare", "2025-05-14", "2026-10-08"],
        ["Viktor Lind", "Utvecklare", "2025-03-01", "2026-10-22"],
        ["Elin Andersson", "Utvecklare", "2025-02-10", "Ej planerat"],
        ["Alice Forsberg", "Junior utvecklare", "2026-03-18", "2027-03-01"],
        ["Hugo Larsson", "Junior utvecklare", "2026-05-28", "2027-05-01"],
        ["Maria Gustavsson", "Testledare", "2026-01-29", "2026-10-29"],
        ["Johanna Sjöberg", "UX-designer", "2025-09-25", "2026-11-20"],
        ["Daniel Nyström", "Data/AI-specialist", "2026-02-05", "2026-10-05"],
        ["Patrik Öberg", "DevOps-ingenjör", "2024-11-25", "Ej planerat"],
        ["Simon Dahl", "DevOps-ingenjör", "2026-02-26", "2026-11-12"],
    ]
    csv_w(fol / "utvecklingssamtalsregister.csv",
          ["Medarbetare", "Roll", "Senaste samtal", "Nästa planerat"], rows)
    reg("DOC-EMP-003", "employees/utvecklingssamtalsregister.csv", "REGISTER",
        "Utvecklingssamtalsregister", "2026-09-25", "P-004", ["ORG-NORDVIKEN"],
        note="Flera medarbetare har inte haft utvecklingssamtal på över 12 månader.")

    # ---- DOC-EMP-004 Sjukfrånvaro FY25 ----------------------------------------------------------
    hr_doc("DOC-EMP-004", "sjukfranvaro_rapport_fy25.docx",
           "Sjukfrånvarorapport FY2025 (2024-10-01 – 2025-09-30)", "2025-11-03", "P-004",
           [("p", "Total sjukfrånvaro under FY25 uppgick till 4,2 % av ordinarie arbetstid."),
            ("t", ["Kvartal", "Leverans", "Stab/ledning", "Totalt"], [
                ["Q1 (okt–dec)", "4,9 %", "2,4 %", "4,3 %"],
                ["Q2 (jan–mar)", "5,6 %", "2,8 %", "4,9 %"],
                ["Q3 (apr–jun)", "4,4 %", "3,0 %", "4,0 %"],
                ["Q4 (jul–sep)", "4,2 %", "3,4 %", "3,8 %"],
                ["Helår", "4,8 %", "2,9 %", "4,2 %"],
            ]),
            ("p", "Korttidsfrånvaro (1–14 dagar) står för 60 % av frånvaron i leveransteamet.")],
           note="Källa: HR-systemets frånvarorapportering.")

    # ---- DOC-EMP-005 Sjukfrånvaro 2026 (HR, september) ---------------------------------------------
    hr_doc("DOC-EMP-005", "sjukfranvaro_rapport_fy26_hr.docx",
           "Sjukfrånvarorapport FY2026 (2025-10-01 – 2026-09-30)", "2026-09-28", "P-004",
           [("p", "Total sjukfrånvaro under FY26 uppgick till 4,4 % av ordinarie arbetstid (föregående år: 4,2 %)."),
            ("t", ["Kvartal", "Leverans", "Stab/ledning", "Totalt"], [
                ["Q1 (okt–dec 2025)", "3,8 %", "2,6 %", "3,5 %"],
                ["Q2 (jan–mar)", "4,6 %", "2,9 %", "4,1 %"],
                ["Q3 (apr–jun)", "4,9 %", "3,1 %", "4,5 %"],
                ["Q4 (jul–sep)", "5,2 %", "3,2 %", "4,7 %"],
                ["Helår", "4,6 %", "3,0 %", "4,4 %"],
            ]),
            ("p", "Leveransteamets frånvaro ökar under andra halvåret; mönster kopplas till arbetsbelastning (se medarbetarundersökningarna)."),
            ("p", "Källa: HR-systemets frånvarorapportering, manuell sammanställning av Petra Wahlgren.")],
           note="Q1-2026 leveransteamet 3,8 % enligt HR-sammanställningen.")

    # ---- DOC-EMP-006 Sjukfrånvaro 2026 (löneexport, februari) ----------------------------------------
    hr_doc("DOC-EMP-006", "sjukfranvaro_rapport_fy26_loneexport.docx",
           "Sjukfrånvarosammanställning Q1 FY26 – export från lönesystemet", "2026-02-10", "P-003",
           [("p", "Sammanställning av sjukfrånvaro för första kvartalet FY26 (oktober–december 2025), exporterad ur lönesystemet (Löneportalen)."),
            ("t", ["Team", "Sjukfrånvaro Q1"], [
                ["Leveransteamet", "5,1 %"],
                ["Stab/ledning", "2,6 %"],
                ["Totalt", "4,5 %"],
            ]),
            ("p", "Notering: exporten bygger på frånvarokoder registrerade i lönesystemet, inklusive sjukfrånvaro utbetald som sjuklön. Dagar med sjukavdrag men utan sjuklön ingår inte."),
            ("p", "Källa: Löneportalen, export 2026-02-10 (Anders Bergström).")],
           note="Q1-2026 leveransteamet 5,1 % enligt löneexporten (avviker från HR-rapporten).")

    # ---- DOC-EMP-007 Kompetensmatris ---------------------------------------------------------------
    comp_rows = [
        ["Daniel Nyström", "Data/AI", "4", "1", "0", "0", "0", "0", "0"],
        ["Tomas Berg", "Lösningsarkitekt", "1", "4", "0", "0", "2", "0", "0"],
        ["Nadia Haddad", "Lösningsarkitekt", "1", "3", "0", "0", "2", "0", "0"],
        ["Maria Gustavsson", "Testledare", "0", "0", "4", "0", "1", "0", "0"],
        ["Patrik Öberg", "DevOps", "1", "1", "0", "3", "0", "0", "0"],
        ["Simon Dahl", "DevOps", "0", "1", "0", "3", "0", "0", "0"],
        ["Fredrik Lund", "Senior utvecklare", "1", "2", "1", "2", "0", "0", "0"],
        ["Emma Persson", "Senior utvecklare", "0", "2", "2", "2", "0", "0", "0"],
        ["Johan Wall", "Senior utvecklare", "0", "2", "1", "2", "0", "0", "0"],
        ["Oskar Nilsson", "Senior utvecklare", "0", "1", "2", "1", "0", "0", "0"],
        ["Camilla Westin", "Senior utvecklare", "0", "1", "2", "1", "0", "0", "0"],
        ["Viktor Lind", "Utvecklare", "0", "1", "1", "1", "0", "0", "0"],
        ["Elin Andersson", "Utvecklare", "0", "1", "1", "1", "0", "0", "0"],
        ["Alice Forsberg", "Junior utvecklare", "0", "0", "1", "0", "0", "0", "0"],
        ["Hugo Larsson", "Junior utvecklare", "0", "0", "1", "0", "0", "0", "0"],
        ["Johanna Sjöberg", "UX-designer", "0", "0", "0", "0", "0", "3", "0"],
        ["David Ekström", "Projektledare", "0", "0", "0", "0", "0", "0", "3"],
        ["Karin Olsson", "Projektledare", "0", "0", "0", "0", "0", "0", "3"],
        ["Klara Månsson (lämnade 2026-09-30)", "Support", "0", "0", "0", "0", "0", "0", "0"],
    ]
    csv_w(fol / "kompetensmatris.csv",
          ["Medarbetare", "Roll", "Data/AI (1–4)", "Arkitektur (1–4)", "Test/testledning (1–4)",
           "DevOps (1–4)", "Utveckling (1–4)", "UX (1–4)", "Projektledning (1–4)"],
          comp_rows)
    reg("DOC-EMP-007", "employees/kompetensmatris.csv", "REGISTER",
        "Kompetensmatris", "2026-09-25", "P-007", ["ORG-NORDVIKEN"],
        note="Ensamkompetenser: Daniel Nyström (data/AI), Tomas Berg (arkitektur), Maria Gustavsson (testledning).")

    # ---- DOC-EMP-008 Rekrytering arkitekt -----------------------------------------------------------
    hr_doc("DOC-EMP-008", "rekrytering_arkitekt.docx",
           "Rekryteringsärende REC-2025-01 – Lösningsarkitekt (tillsatt)", "2026-03-31", "P-004",
           [("b", "Kravprofil"),
            ("p", "Minst 10 års erfarenhet av systemutveckling, varav minst 4 år som lösningsarkitekt. Dokumenterad erfarenhet av molnarkitektur (Azure/AWS), integrationsplattformar och säkerhetsarkitektur. God förmåga att leda tekniska dialoger med kunder."),
            ("b", "Kandidatutvärdering (max 100 poäng)"),
            ("t", ["Kandidat", "Teknisk bedömning", "Kunddialog", "Kulturell match", "Totalt"], [
                ["A – Nadia Haddad", "45", "25", "18", "88"],
                ["B", "40", "20", "14", "74"],
                ["C", "32", "17", "12", "61"],
            ]),
            ("b", "Beslut"),
            ("p", "Kandidat A (Nadia Haddad) erbjuds tjänsten. Start 2026-05-04, månadslön 72 000 kr. Rekryteringen genomfördes via Talangjakten AB.")],
           evt=["EVT-057"], note="Roll tillsatt av Nadia Haddad 2026-05-04.")

    # ---- DOC-EMP-009 Rekrytering DevOps (öppen) --------------------------------------------------------
    hr_doc("DOC-EMP-009", "rekrytering_devops.docx",
           "Rekryteringsärende REC-2026-02 – DevOps-ingenjör (öppen)", "2026-09-30", "P-004",
           [("b", "Kravprofil"),
            ("p", "Erfarenhet av CI/CD (Bygglådan eller motsvarande), containerbaserad drift, IaC samt övervakning (Vakthuset). Minst 3 års erfarenhet. Erfarenhet av lönesystemintegrationer meriterande."),
            ("b", "Kandidatutvärdering"),
            ("t", ["Kandidat", "Teknisk bedömning", "Automatisering", "Kulturell match", "Totalt"], [
                ["A", "38", "19", "14", "71"],
                ["B", "34", "17", "12", "63"],
            ]),
            ("b", "Status"),
            ("p", "Intervjuomgång 2 planerad v43. Beslut väntas 2026-10-30. Rekryteringen pausades i kostnadsprogrammet men återupptogs 2026-09-20 på grund av integrationsproblemen (se DOC-IT-001).")],
           note="Ärende öppet per 2026-10-18.")

    # ---- DOC-EMP-010 Rekrytering supportansvarig (öppen) --------------------------------------------------
    hr_doc("DOC-EMP-010", "rekrytering_supportansvarig.docx",
           "Rekryteringsärende REC-2026-03 – Supportansvarig (öppen, brådskande)", "2026-10-02", "P-004",
           [("b", "Kravprofil"),
            ("p", "Erfarenhet av applikationssupport och incidenthantering, gärna inom vård-IT. Förmåga att bygga supportprocesser, svarstidsmål och kunddialog. God svenska i tal och skrift."),
            ("b", "Kandidatutvärdering"),
            ("t", ["Kandidat", "Supportmetodik", "Teknisk bredd", "Kunddialog", "Totalt"], [
                ["A", "35", "18", "15", "68"],
                ["B", "30", "16", "13", "59"],
            ]),
            ("b", "Status"),
            ("p", "Annons ute sedan 2026-09-05. Rollen är kritisk: supporten har saknat ansvarig sedan Klara Månsson lämnade 2026-09-30 och klagomålen från Blåklintens Vård har eskalerat (se DOC-COM-002).")],
           note="Ärende öppet per 2026-10-18.")

    # ---- DOC-EMP-011 Utbildningsplan 2026 ----------------------------------------------------------------
    hr_doc("DOC-EMP-011", "utbildningsplan_2026.docx",
           "Utbildningsplan 2026", "2026-01-15", "P-004",
           [("p", "Budget 2026: 450 000 kr (Kompetensbron AB samt interna utbildningar)."),
            ("t", ["Utbildning", "Målgrupp", "Planerad", "Status"], [
                ["AI-introduktion (policy och verktyg)", "Alla", "2026-03", "Genomförd"],
                ["Azure-arkitektur", "Arkitekter, DevOps", "2026-04", "Genomförd"],
                ["Säkerhetsmedvetenhet (årlig)", "Alla", "2026-10", "Planerad"],
                ["Ledarskap för projektledare", "PM, chefer", "2026-11", "Planerad – risk att skjutas p.g.a. kostnadsprogram"],
                ["Testautomatisering", "Test, utvecklare", "2026-05", "Genomförd"],
                ["Data/AI-fördjupning", "Data/AI", "2026-09", "Delvis – endast Daniel deltog"],
            ])],
           note="Fördjupningen i data/AI nådde bara en deltagare (nyckelpersonsrisk).")

    # ---- DOC-EMP-012 SAM ----------------------------------------------------------------------------
    hr_doc("DOC-EMP-012", "sam_riskbedomning_arbetsmiljo.docx",
           "SAM – riskbedömning arbetsmiljö 2026", "2026-02-10", "P-004",
           [("p", "Riskbedömning enligt AFS 2001:1 (systematiskt arbetsmiljöarbete), genomförd med skyddsombud och ledningsgrupp."),
            ("t", ["Risk", "Sannolikhet", "Konsekvens", "Åtgärd", "Status"], [
                ["Hög arbetsbelastning i leveransteamet (övertid, kunddeadlines)", "Hög", "Medel", "Beläggningsmål per team, övertidsöversyn, förstärkning med underkonsulter", "Pågående"],
                ["Ensamkompetens inom data/AI, arkitektur och testledning", "Medel", "Hög", "Kunskapsöverföring och breddning (se kompetensmatris)", "Ej startad"],
                ["Skärmarbete och stillasittande", "Hög", "Låg", "Ergonomiskt stöd, rastrutiner", "Genomförd"],
                ["Arbetsmiljöansvar för inhyrd personal (underkonsulter)", "Medel", "Medel", "Tydliggöra ansvarsfördelningen i avtal med underkonsulter", "Pågående – otydligt i nuvarande avtal"],
                ["Ensamarbete vid kvällsjour", "Låg", "Låg", "Jourschema med två i beredskap", "Genomförd"],
            ]),
            ("p", "Uppföljning: nästa riskbedömning 2027-02.")],
           note="Underkonsulternas arbetsmiljöansvar markerat som otydligt i avtalen.")

    # ---- DOC-EMP-013 Personalomsättningsrapport FY26 ----------------------------------------------------------
    hr_doc("DOC-EMP-013", "personalomsattning_fy26.docx",
           "Personalomsättningsrapport FY2026", "2026-09-30", "P-004",
           [("p", "Under räkenskapsåret 2025-10-01 – 2026-09-30 har 8 medarbetare lämnat bolaget. Omsättningen motsvarar cirka 28 % av medelantalet anställda (29)."),
            ("t", ["Medarbetare", "Roll", "Avgångsdatum", "Orsak"], [
                ["Rasmus Holm", "Senior utvecklare", "2025-10-31", "Rekryterad av kund (SEAB)"],
                ["Robin Åkerlund", "Utvecklare", "2026-01-31", "Provanställning avslutad"],
                ["Anna Westberg", "Marknadskoordinator", "2026-02-28", "Arbetsbelastning"],
                ["Magnus Ryd", "Projektledare", "2026-03-31", "Utmattningsrelaterat"],
                ["Lukas Ek", "Dataanalytiker", "2026-05-31", "Rekryterad av underkonsult"],
                ["Sofia Lindgren", "Senior utvecklare", "2026-06-30", "Rekryterad av kund (Polstjärnan)"],
                ["Björn Falk", "Utvecklare", "2026-08-31", "Flytt utomlands"],
                ["Klara Månsson", "Supportansvarig", "2026-09-30", "Ny tjänst"],
            ]),
            ("p", "Observera: avgångarna har minskat leveranskapaciteten med fyra utvecklare/projektledare. Supporten saknar ansvarig fr.o.m. 2026-10-01."),
            ("p", "Avgränsning: rapporten avser räkenskapsåret (okt–sep). Räknat per kalenderår 2026 uppgår antalet avgångar till 7, eftersom Rasmus Holms avgång (2025-10-31) ligger utanför kalenderåret."),
            ("p", "Källa: HR-systemet (Personalen AB), sammanställning av Petra Wahlgren.")],
           note="8 avgångar under räkenskapsåret FY26; per kalenderår 2026 blir antalet 7 (Rasmus Holm lämnade 2025-10-31).")


# ---------------------------------------------------------------------------
# customers/
# ---------------------------------------------------------------------------

def section_customers(m: Model) -> None:
    fol = F["customers"]

    # ---- CRM-export -------------------------------------------------------
    rows: list[list] = []
    cid_name = {c.id: c.name for c in m.customers}
    cid_seg = {c.id: c.segment for c in m.customers}

    def cust(cid):
        return cid_name.get(cid, cid)

    # -- won: stora affärer (kontrakt ur modellen) ---------------------------
    large_won = [
        ("CTR-2024-010", "CUS-001", "SE-Förvaltning (320 kkr/mån)", "MANAGED", 12),
        ("CTR-2025-014", "CUS-003", "FS-Förvaltning (85 kkr/mån)", "MANAGED", 12),
        ("CTR-2025-020", "CUS-011", "NH-Förvaltning (95 kkr/mån)", "MANAGED", 12),
        ("CTR-2025-011", "CUS-006", "TS-Produktionsportal", "FAST", 1),
        ("CTR-2025-006", "CUS-014", "SV-Molnmigrering", "FAST", 1),
        ("CTR-2025-002", "CUS-012", "ÅB-Bostadsportal", "FAST", 1),
        ("CTR-2025-009", "CUS-017", "LL-Spårbarhet", "FAST", 1),
        ("CTR-2025-016", "CUS-022", "LM-Lärplattform", "FAST", 1),
        ("CTR-2025-019", "CUS-020", "TR-Skogsportal", "FAST", 1),
        ("CTR-2026-001", "CUS-025", "SU-Produktionssystem", "FAST", 1),
        ("CTR-2026-004", "CUS-001", "SE-Billing – tilläggsavtal", "FAST", 1),
        ("CTR-2026-002", "CUS-001", "Ramavtal SEAB – förlängning (1 180 kr/h)", "TIME", "SCH-002"),
        ("CTR-2024-030", "CUS-008", "MM-Underhållssystem (1 030 kr/h)", "TIME", "SCH-011"),
        ("CTR-2024-014", "CUS-004", "KL-Vårdportal (1 090 kr/h)", "TIME", "SCH-007"),
    ]
    for ctr_id, cus_id, label, model, mult in large_won:
        c = m.contract(ctr_id)
        if model == "MANAGED":
            val = (c.amount or 0) * mult
        elif model == "FAST":
            val = c.amount or 0
        else:
            hours = _fy26_hours(m, mult)
            val = round((c.rate or 0) * hours)
        rows.append(["OPP-L-" + ctr_id, cust(cus_id), cid_seg[cus_id], label,
                     "Won", val, 100, "Sara Holm", str(c.signed), str(c.signed),
                     str(c.signed), "Won", ctr_id, "Kontrakt signerat"])

    # -- won: små affärer (CTR-SM) -------------------------------------------
    small_won_ids = ["CTR-SM-051", "CTR-SM-053", "CTR-SM-054", "CTR-SM-055",
                     "CTR-SM-056", "CTR-SM-058", "CTR-SM-059", "CTR-SM-060",
                     "CTR-SM-062", "CTR-SM-063", "CTR-SM-064", "CTR-SM-068",
                     "CTR-SM-071", "CTR-SM-074"]
    for ctr_id in small_won_ids:
        c = m.contract(ctr_id)
        sch = next((s for s in m.schedules if s.contract_id == ctr_id), None)
        hours = _fy26_hours(m, sch.id) if sch else 200.0
        val = round((c.rate or 950) * (hours if hours > 0 else 200))
        rows.append(["OPP-S-" + ctr_id, cust(c.counterparty_id), cid_seg.get(c.counterparty_id, "SMB"),
                     c.title, "Won", val, 100, "Lisa Sundberg", str(c.signed),
                     str(c.signed), str(c.signed), "Won", ctr_id, "Mindre uppdrag"])

    # -- förlorade stora affärer ----------------------------------------------
    large_lost = [
        ("OPP-L-L01", "CUS-004", "Vårdportal fas 2", 4200000, "2025-11-14", "Valde annan leverantör (lägre pris)"),
        ("OPP-L-L02", "CUS-011", "Ny logistikplattform", 2800000, "2026-04-09", "Budgetstopp hos kunden"),
        ("OPP-L-L03", "CUS-003", "Intranätutveckling", 2100000, "2026-02-13", "Upphandling – lägre pris"),
        ("OPP-L-L04", "CUS-002", "Integrationsprojekt", 1800000, "2025-06-27", "Kunden sköt upp projektet"),
        ("OPP-L-L05", "CUS-001", "AI-plattform", 3600000, "2026-05-08", "SEAB bygger internt"),
        ("OPP-L-L06", "CUS-015", "Försäkringsportal fas 2", 2400000, "2026-06-19", "Kunden valde större leverantör"),
        ("OPP-L-L07", "CUS-006", "Underhållsavtal TS", 1200000, "2026-07-10", "Efter tvisten ville kunden inte förlänga"),
        ("OPP-L-L08", "CUS-005", "Biljettapp", 1500000, "2025-08-29", "Pris"),
        ("OPP-L-L09", "CUS-013", "Mobilapp fältarbete", 1900000, "2026-03-20", "Pausad av kunden"),
        ("OPP-L-L10", "CUS-009", "E-handelsförvaltning", 1450000, "2025-03-31", "Tvist – samarbetet avslutades"),
        ("OPP-L-L11", "CUS-008", "Förnyelse MM-avtalet", 1240000, "2026-06-30", "Konkurrent 20 % billigare"),
        ("OPP-L-L12", "CUS-010", "E-handel fas 2", 950000, "2025-12-08", "Kunden i konkurs"),
        ("OPP-L-L13", "CUS-012", "Förvaltningsavtal ÅB", 900000, "2026-04-24", "Kunden avvaktar"),
        ("OPP-L-L14", "CUS-011", "Integrationsplattform", 1650000, "2025-10-17", "Pris"),
        ("OPP-L-L15", "CUS-001", "Dataplattform", 2900000, "2026-08-21", "SEAB valde intern lösning"),
        ("OPP-L-L16", "CUS-004", "Larmportal", 1300000, "2026-07-31", "Politisk omprioritering"),
        ("OPP-L-L17", "CUS-017", "Spårbarhet fas 2", 880000, "2026-05-15", "Kunden sköt upp"),
        ("OPP-L-L18", "CUS-014", "Driftövervakning", 1100000, "2026-06-26", "Pris"),
        ("OPP-L-L19", "CUS-015", "Dokumenthantering", 1400000, "2025-12-19", "Kunden valde befintlig leverantör"),
        ("OPP-L-L20", "CUS-002", "E-arkiv", 2300000, "2026-03-06", "Upphandling pågår hos kunden"),
        ("OPP-L-L21", "CUS-003", "Ärendehantering", 1700000, "2025-11-28", "Pris"),
        ("OPP-L-L22", "CUS-006", "MES-integration", 1350000, "2026-09-11", "Kunden avvaktar"),
        ("OPP-L-L23", "CUS-013", "Datalager", 2500000, "2026-01-30", "Valde Dataverket Nord"),
        ("OPP-L-L24", "CUS-005", "Passagerarsystem", 2000000, "2026-05-29", "Budget"),
        ("OPP-L-L25", "CUS-001", "Säkerhetsöversyn", 1600000, "2026-02-27", "SEAB valde intern resurs"),
        ("OPP-L-L26", "CUS-011", "API-plattform", 1250000, "2026-06-12", "Pris"),
        ("OPP-L-L27", "CUS-022", "Förvaltning lärplattform", 960000, "2026-09-25", "Kunden avvaktar"),
        ("OPP-L-L28", "CUS-015", "AI-understöd skadereglering", 2200000, "2026-07-24", "Krav på datacenter i Sverige"),
        ("OPP-L-L29", "CUS-002", "Intranätmigrering", 1900000, "2026-04-17", "Upphandling – förlorad"),
        ("OPP-L-L30", "CUS-003", "E-tjänster", 2600000, "2026-08-14", "Upphandling – förlorad"),
        ("OPP-L-L31", "CUS-001", "Fakturaportal mobil", 1450000, "2026-09-04", "SEAB valde annan leverantör"),
        ("OPP-L-L32", "CUS-004", "Journalsystem", 3800000, "2026-02-20", "Regionen valde större leverantör"),
        ("OPP-L-L33", "CUS-013", "IoT-plattform", 2100000, "2025-10-24", "Pris"),
        ("OPP-L-L34", "CUS-006", "Underhållssystem", 1700000, "2025-12-05", "Kunden valde billigare"),
        ("OPP-L-L35", "CUS-011", "Kundportal", 1550000, "2026-08-28", "Avvaktar budget"),
        ("OPP-L-L36", "CUS-015", "Mobilapp", 1800000, "2026-03-27", "Kunden sköt upp"),
        ("OPP-L-L37", "CUS-002", "AI-assistent för handläggare", 1500000, "2026-07-10", "Upphandling avbruten"),
        ("OPP-L-L38", "CUS-005", "Driftövervakning", 1250000, "2026-09-18", "Pris"),
        ("OPP-L-L39", "CUS-015", "Testautomatisering", 1100000, "2026-04-30", "Kunden valde befintlig leverantör"),
        ("OPP-L-L40", "CUS-001", "BI-lösning", 2100000, "2025-11-07", "SEAB valde intern lösning"),
        ("OPP-L-L41", "CUS-011", "Mobilapp hamnarbetare", 1350000, "2026-08-05", "Budget"),
        ("OPP-L-L42", "CUS-006", "IoT-sensorplattform", 1600000, "2026-02-25", "Kunden sköt upp"),
    ]
    for i, (oid, cus_id, label, val, closed, why) in enumerate(large_lost):
        from datetime import date as _d, timedelta as _td
        created = (_d.fromisoformat(closed) - _td(days=60 + (i * 11) % 90)).isoformat()
        rows.append([oid, cust(cus_id), cid_seg[cus_id], label, "Lost", val, 0,
                     "Sara Holm", created, closed, closed, "Lost", "", why])

    # -- förlorade små affärer --------------------------------------------------
    small_lost = [
        ("OPP-S-L01", "CUS-026", "Bokningssystem", 180000, "2026-04-18", "Pris"),
        ("OPP-S-L02", "CUS-027", "Leveransapp", 220000, "2025-09-19", "Valde billigare"),
        ("OPP-S-L03", "CUS-029", "E-handel", 160000, "2026-02-27", "Avvaktar"),
        ("OPP-S-L04", "CUS-030", "Webbplats", 240000, "2026-05-22", "Pris"),
        ("OPP-S-L05", "CUS-032", "Bokningssystem", 210000, "2026-07-17", "Valde annan byrå"),
        ("OPP-S-L06", "CUS-033", "Tidtabellsapp", 260000, "2025-11-21", "Budget"),
        ("OPP-S-L07", "CUS-034", "Biljettsystem", 190000, "2026-03-13", "Pris"),
        ("OPP-S-L08", "CUS-035", "Ärendehantering", 150000, "2025-12-12", "Valde annan leverantör"),
        ("OPP-S-L09", "CUS-037", "Hemsida", 175000, "2026-06-05", "Pris"),
        ("OPP-S-L10", "CUS-038", "Butikssystem", 140000, "2025-08-15", "Avvaktar"),
        ("OPP-S-L11", "CUS-039", "Prenumerationssystem", 230000, "2026-01-23", "Budget"),
        ("OPP-S-L12", "CUS-044", "Beställningsapp", 165000, "2026-04-10", "Pris"),
        ("OPP-S-L13", "CUS-045", "Larmportal", 280000, "2026-08-07", "Krav på certifiering"),
        ("OPP-S-L14", "CUS-046", "Chattsystem", 250000, "2026-09-18", "Valde annan leverantör"),
        ("OPP-S-L15", "CUS-047", "Offerthantering", 185000, "2025-10-31", "Pris"),
        ("OPP-S-L16", "CUS-043", "Loggbok fiskeflotta", 155000, "2026-02-06", "Avvaktar"),
        ("OPP-S-L17", "CUS-050", "E-handel", 320000, "2026-06-13", "Valde billigare"),
    ]
    for i, (oid, cus_id, label, val, closed, why) in enumerate(small_lost):
        from datetime import date as _d, timedelta as _td
        created = (_d.fromisoformat(closed) - _td(days=45 + (i * 9) % 70)).isoformat()
        rows.append([oid, cust(cus_id), cid_seg[cus_id], label, "Lost", val, 0,
                     "Lisa Sundberg", created, closed, closed, "Lost", "", why])

    # -- öppna affärer (pipeline, analysdatum 2026-10-18) ------------------------
    open_rows = [
        # (id, kund, tjänst, stadium, belopp, sannolikhet, ägare, skapad, senast)
        ("OPP-O-01", "CUS-001", "AI-stöd fakturering", "Negotiation", 1900000, 70, "Maja Lindqvist", "2026-06-12", "2026-10-02"),
        ("OPP-O-02", "CUS-004", "Nytt ramavtal digitalisering", "Negotiation", 2400000, 50, "Sara Holm", "2026-04-02", "2026-07-22"),
        ("OPP-O-03", "CUS-002", "E-tjänstplattform", "Negotiation", 1700000, 60, "Sara Holm", "2026-03-10", "2026-10-08"),
        ("OPP-O-04", "CUS-013", "Dataplattform", "Negotiation", 1900000, 55, "Sara Holm", "2026-05-19", "2026-09-30"),
        ("OPP-O-05", "CUS-033", "Underhållsavtal tidtabellsapp", "Negotiation", 440000, 60, "Lisa Sundberg", "2026-08-04", "2026-09-26"),
        ("OPP-O-06", "CUS-040", "Kundportal", "Proposal", 600000, 30, "Lisa Sundberg", "2026-06-09", "2026-08-02"),
        ("OPP-O-07", "CUS-024", "CRM- och lojalitetssystem", "Negotiation", 600000, 50, "Sara Holm", "2026-08-11", "2026-10-10"),
        ("OPP-O-08", "CUS-045", "Ärendehanteringssystem", "Negotiation", 480000, 50, "Lisa Sundberg", "2026-09-01", "2026-10-09"),
        ("OPP-O-09", "CUS-048", "Molnmigrering", "Negotiation", 520000, 55, "Lisa Sundberg", "2026-08-25", "2026-10-08"),
        ("OPP-O-10", "CUS-049", "Logistikportal", "Negotiation", 470000, 50, "Lisa Sundberg", "2026-09-08", "2026-09-28"),
        ("OPP-O-11", "CUS-018", "Utökning bokningssystem", "Negotiation", 400000, 55, "Lisa Sundberg", "2026-09-15", "2026-10-06"),
        ("OPP-O-12", "CUS-015", "AI-understöd", "Proposal", 900000, 20, "Sara Holm", "2026-07-07", "2026-10-14"),
        ("OPP-O-13", "CUS-046", "Chatbotsystem", "Discovery", 550000, 25, "Lisa Sundberg", "2026-09-22", "2026-10-15"),
        ("OPP-O-14", "CUS-050", "E-handel", "Proposal", 330000, 30, "Lisa Sundberg", "2026-07-14", "2026-08-30"),
        ("OPP-O-15", "CUS-039", "Lärplattform", "Discovery", 420000, 20, "Lisa Sundberg", "2026-09-02", "2026-09-22"),
        ("OPP-O-16", "CUS-031", "Dokumenthantering", "Proposal", 300000, 35, "Lisa Sundberg", "2026-08-18", "2026-09-15"),
    ]
    for oid, cus_id, label, stage, val, prob, owner, created, last in open_rows:
        rows.append([oid, cust(cus_id), cid_seg[cus_id], label, stage, val, prob,
                     owner, created, last, "", "Open", "", ""])

    csv_w(fol / "crm_export.csv",
          ["opportunity_id", "kund", "segment", "tjanst", "stadium", "belopp_sek",
           "sannolikhet_pct", "agare", "skapad", "senast_aktivitet", "stangningsdatum",
           "utfall", "avtal_id", "kommentar"], rows)
    reg("DOC-CRM-001", "customers/crm_export.csv", "CRM",
        "CRM-export (pipeline, 2024–2026)", "2026-10-18", "SYSTEM",
        sorted({r[1] for r in rows})[:40],
        note="Export 2026-10-18. Öppen pipeline ca 13,3 MSEK; committed (Negotiation, Q4) ca 10,8 MSEK.")

    # ---- Offerter ×12 --------------------------------------------------------
    offers = [
        ("DOC-OFF-001", "offert_2026-09_fjallporten.docx", "OFF-2026-09", "Fjällporten Hotell AB", "CRM- och lojalitetssystem",
         "Fast pris 595 000 kr exkl. moms (implementering) + förvaltning 24 000 kr/mån", "2026-10-20", "Sara Holm"),
        ("DOC-OFF-002", "offert_2026-10_skymningsvakten.docx", "OFF-2026-10", "Skymningsvakten AB", "Ärendehanteringssystem",
         "Fast pris 480 000 kr exkl. moms", "2026-10-23", "Lisa Sundberg"),
        ("DOC-OFF-003", "offert_2026-11_askmolns_data.docx", "OFF-2026-11", "Åskmolns Data AB", "Molnmigrering till Azure",
         "Fast pris 520 000 kr exkl. moms", "2026-10-24", "Lisa Sundberg"),
        ("DOC-OFF-004", "offert_2026-12_stormvindens.docx", "OFF-2026-12", "Stormvindens Logistik AB", "Logistikportal",
         "Fast pris 470 000 kr exkl. moms", "2026-11-15", "Lisa Sundberg"),
        ("DOC-OFF-005", "offert_2026-13_guldstaden.docx", "OFF-2026-13", "Guldstaden Revision AB", "Dokumenthanteringssystem",
         "Fast pris 300 000 kr exkl. moms", "2026-11-10", "Lisa Sundberg"),
        ("DOC-OFF-006", "offert_2026-14_kristallkronan.docx", "OFF-2026-14", "Kristallkronans Smycken AB", "E-handelsplattform",
         "Fast pris 330 000 kr exkl. moms", "2026-12-05", "Lisa Sundberg"),
        ("DOC-OFF-007", "offert_2026-15_hostlovet.docx", "OFF-2026-15", "Höstlövets Förlag AB", "Lärplattform för kurser",
         "Fast pris 420 000 kr exkl. moms", "2026-11-30", "Lisa Sundberg"),
        ("DOC-OFF-008", "offert_2026-16_nattugglan.docx", "OFF-2026-16", "Nattugglans Kundservice AB", "Chatbotsystem med AI",
         "Fast pris 550 000 kr exkl. moms", "2026-11-21", "Lisa Sundberg"),
        ("DOC-OFF-009", "offert_2026-17_polstjarnan_ai.docx", "OFF-2026-17", "Polstjärnan Försäkring AB", "AI-understöd för skadereglering (förstudie)",
         "Löpande räkning 1 350 kr/h, uppskattad omfattning 650 h", "2026-12-12", "Sara Holm"),
        ("DOC-OFF-010", "offert_2026-18_graviken.docx", "OFF-2026-18", "Gråvikens kommun", "E-tjänstplattform",
         "Löpande räkning 1 100 kr/h, uppskattad omfattning 1 500 h", "2026-12-18", "Sara Holm"),
        ("DOC-OFF-011", "offert_2026-19_gruvberget.docx", "OFF-2026-19", "Gruvbergets Mineral AB", "Dataplattform",
         "Fast pris 1 900 000 kr exkl. moms", "2026-12-20", "Sara Holm"),
        ("DOC-OFF-012", "offert_2026-20_varfloden.docx", "OFF-2026-20", "Vårflodens Energi AB", "Kundportal",
         "Fast pris 600 000 kr exkl. moms", "2026-10-31", "Lisa Sundberg"),
    ]
    for doc_id, fname, offno, kund, tjanst, pris, giltig, author in offers:
        d = new_doc()
        head(d, f"Offert {offno}", "Offertdatum 2026-10-01", author, doc_id)
        kv(d, "Kund", kund)
        kv(d, "Tjänst", tjanst)
        kv(d, "Pris", pris)
        kv(d, "Giltig t.o.m.", giltig)
        kv(d, "Betalningsvillkor", "30 dagar netto")
        para(d, "")
        para(d, "Omfattning")
        para(d, f"Offerten omfattar {tjanst.lower()} inklusive workshops, implementation, tester och överlämning. Support ingår i 3 månader efter driftsättning.")
        para(d, "Förutsättningar: tillgång till kundens miljöer samt beslutade kontaktpersoner. Ändringar i omfattning faktureras enligt vid var tid gällande timprislista.")
        para(d, "Offerten är giltig till och med angivet datum. Vid frågor kontakta undertecknad.")
        right(d, author)
        save(d, fol / fname)
        reg(doc_id, f"customers/{fname}", "OFFERT", f"Offert {offno} – {kund}",
            "2026-10-01", "P-005" if author == "Sara Holm" else "P-006", ["ORG-NORDVIKEN"],
            valid_to=giltig)

    # ---- Förlorade-affärer register -------------------------------------------
    lost_rows = [
        ["Mossbackens Mekaniska AB", "MM-Underhållssystem", "2026-06-30", "Pris (konkurrent 20 % lägre)", "Blå Ocean IT AB"],
        ["Örby Handel & Logistik AB", "ÖH-Webbplattform (tvist)", "2025-03-31", "Tvist om acceptans", "–"],
        ["Sjöstadens Bryggeri AB", "SB-E-handel", "2025-12-08", "Kunden i konkurs (kundförlust 220 065 kr)", "–"],
        ["Kustlandets region", "Vårdportal fas 2", "2025-11-14", "Valde annan leverantör", "Större konsultbolag"],
        ["Norrhamns Hamn AB", "Ny logistikplattform", "2026-04-09", "Budgetstopp", "–"],
        ["SEAB", "AI-plattform", "2026-05-08", "Kunden bygger internt", "–"],
        ["Polstjärnan Försäkring AB", "Försäkringsportal fas 2", "2026-06-19", "Valde större leverantör", "Större konsultbolag"],
        ["Gruvbergets Mineral AB", "Datalager", "2026-01-30", "Valde Dataverket Nord", "Dataverket Nord AB"],
    ]
    csv_w(fol / "forlorade_affarer.csv",
          ["Kund", "Tjänst", "Förlorad datum", "Orsak", "Vinnande konkurrent"], lost_rows)
    reg("DOC-CRM-002", "customers/forlorade_affarer.csv", "REGISTER",
        "Förlorade affärer", "2026-09-30", "P-005", ["ORG-NORDVIKEN", "CUS-008", "CUS-009", "CUS-010"])

    # ---- Kundmötesanteckningar ×6 -------------------------------------------------
    def mote(doc_id, fname, kund, datum, author, deltagare, punkter):
        d = new_doc()
        head(d, f"Kundmötesanteckningar – {kund}", datum, author, doc_id)
        kv(d, "Deltagare", deltagare)
        para(d, "")
        for i, (rub, txt) in enumerate(punkter, 1):
            para(d, f"{i}. {rub}", bold=True)
            para(d, txt)
        save(d, fol / fname)
        reg(doc_id, f"customers/{fname}", "PROTOKOLL", f"Kundmötesanteckningar – {kund}",
            datum, "P-005" if author == "Sara Holm" else "P-006", ["ORG-NORDVIKEN"])

    mote("DOC-CRM-003", "kundmote_2026-01-21_seab.docx", "Skogsbygdens Energi AB", "2026-01-21", "Sara Holm",
         "Sara Holm, Erik Norén; Björn Sandqvist, Ulrika Dahl (SEAB)",
         [("Ramavtalsförlängning", "SEAB bekräftar förlängningen till 2028-01-31 (signerat 2026-01-15). Volymen för SE-Integration väntas öka."),
          ("SE-Billing", "Kunden uttrycker oro för förseningen; vill ha tydligare prognosrapportering."),
          ("Citat", "Björn: 'Ni levererar helt enkelt – det är därför vi växer med er.'")])

    mote("DOC-CRM-004", "kundmote_2026-04-14_graviken.docx", "Gråvikens kommun", "2026-04-14", "Sara Holm",
         "Sara Holm, Karin Olsson; Åsa Bergman (Gråvikens kommun)",
         [("GV-Digitalisering", "Leverans enligt plan. Kommunen efterfrågar utbildningsinsatser för verksamheten."),
          ("Nya behov", "E-tjänstplattform diskuterades; vi ska lämna en offert före sommaren."),
          ("Notering", "Indexklausulen i ramavtalet togs inte upp av någon part.")])

    mote("DOC-CRM-005", "kundmote_2026-06-03_polstjarnan.docx", "Polstjärnan Försäkring AB", "2026-06-03", "Sara Holm",
         "Sara Holm, Emma Persson; representanter från Polstjärnan Försäkring",
         [("PF-Kundportal", "Stabilt läge; testinsatserna via Testhuset fungerar bra."),
          ("AI-intresse", "Kunden vill utforska AI-understöd i skaderegleringen. Förstudie diskuterad."),
          ("Citat", "Kund: 'Ni förstår vår bransch bättre än de stora bolagen.'")])

    mote("DOC-CRM-006", "kundmote_2026-08-19_gruvberget.docx", "Gruvbergets Mineral AB", "2026-08-19", "Sara Holm",
         "Sara Holm, Daniel Nyström; Roger Lund (Gruvbergets Mineral)",
         [("GM-Bergdatasystem", "Drift och utveckling löper på. Dataverket Nord fortsätter som underkonsult."),
          ("Dataplattform", "Kunden vill ha en utökad dataplattform; vi tar fram en offert till oktober.")])

    mote("DOC-CRM-007", "kundmote_2026-09-12_blaklinten.docx", "Blåklintens Vård AB", "2026-09-12", "Sara Holm",
         "Sara Holm; Ingrid Holm (Blåklintens Vård)",
         [("Support", "Genomgång av åtgärdsplanen för supporten (svarstidsmål, bemanning). Kunden är fortsatt kritisk men beredd att avvakta."),
          ("Avtal", "Kunden öppnade för att diskutera avtalsvillkoren vid nästa kvartalsmöte.")])

    mote("DOC-CRM-008", "kundmote_2026-09-25_kustlandet.docx", "Kustlandets region", "2026-09-25", "Sara Holm",
         "Sara Holm; regionens digitaliseringschef",
         [("Ramavtalsdialog", "Regionen planerar en ny upphandling. Vår dialog har legat nere sedan juli – återupptas nu."),
          ("Krav", "Regionen efterfrågar lokal närvaro och referenser från offentlig sektor.")])

    # ---- Klagomålsregister ----------------------------------------------------------
    comp_rows = [
        ["CL-2024-01", "Norrhamns Hamn AB", "NH-Logistikportal", "Prestanda", "2024-09-04", "5", "Åtgärdat (indexoptimering)", "Stängd"],
        ["CL-2024-02", "Norrhamns Hamn AB", "NH-Logistikportal", "Prestanda", "2024-11-06", "4", "Åtgärdat (cachejustering)", "Stängd"],
        ["CL-2024-03", "Norrhamns Hamn AB", "NH-Logistikportal", "Prestanda", "2024-12-18", "3", "Åtgärdsplan DOC-COM-001", "Stängd 2025-01"],
        ["CL-2025-01", "Örby Handel & Logistik AB", "ÖH-Webbplattform", "Acceptans", "2025-02-28", "10", "Tvist – förlikningsförsök pågår", "Öppen"],
        ["CL-2025-02", "Timmervikens Såg AB", "TS-Produktionsportal", "Försening", "2025-11-18", "7", "Återhämtningsplan", "Stängd"],
        ["CL-2026-01", "Blåklintens Vård AB", "BV-Journalsystem", "Svarstider", "2026-02-19", "8", "Åtgärdsplan", "Stängd"],
        ["CL-2026-02", "Blåklintens Vård AB", "BV-Journalsystem", "Svarstider", "2026-05-12", "11", "Åtgärdsplan", "Stängd"],
        ["CL-2026-03", "Blåklintens Vård AB", "BV-Journalsystem", "Svarstider", "2026-09-10", "14", "Åtgärdsplan DOC-COM-002", "Öppen"],
        ["CL-2026-04", "Timmervikens Såg AB", "TS-Produktionsportal", "Försening/vite", "2026-04-21", "9", "Förlikning: kreditnota 90 000 kr 2026-06-30", "Stängd"],
        ["CL-2026-05", "Solvind Kraft AB", "SV-Molnmigrering", "Överlämning", "2026-01-14", "6", "Kompletterande dokumentation", "Stängd"],
    ]
    csv_w(fol / "klagomalsregister.csv",
          ["ID", "Kund", "Tjänst", "Kategori", "Datum", "Svarstid (dagar)", "Åtgärd", "Status"], comp_rows)
    reg("DOC-CRM-009", "customers/klagomalsregister.csv", "REGISTER",
        "Klagomålsregister", "2026-10-01", "P-005",
        ["CUS-011", "CUS-007", "CUS-009", "CUS-006", "CUS-014"],
        note="Norrhamns Hamn ×3 (prestanda), Blåklintens Vård ×3 (svarstider, eskalerande).")

    # ---- Kundsegmentering --------------------------------------------------------------
    d = new_doc()
    head(d, "Kundsegmentering och segmentanalys", "Upprättad 2026-09-15",
         "Sara Holm, Försäljningschef", "DOC-CRM-010", "v1.0")
    table(d, ["Segment", "Kunder", "Omsättning FY25 (netto)", "Omsättning FY26 (netto)", "Utveckling"], [
        ["ENTERPRISE", "Skogsbygdens Energi, Kustbandets Färjor, Timmervikens Såg, Norrhamns Hamn, Gruvbergets Mineral, Polstjärnan Försäkring",
         "20 295 133 kr", "28 348 407 kr", "+39,7 %"],
        ["OFFENTLIG", "Gråvikens kommun, Fyrstadens kommun, Kustlandets region",
         "5 765 831 kr", "4 512 731 kr", "−21,7 %"],
        ["SMB", "Övriga (41 kunder)",
         "16 577 223 kr", "21 377 140 kr", "+29,0 %"],
    ])
    para(d, "Offentlig sektor minskade under FY26: KL-Vårdportalen (Kustlandets region) avslutades 2026-03-31 och inga nya offentliga uppdrag har ersatt volymen. Affärsplanens antagande om +15 % per år i offentlig sektor har därmed inte infriats.")
    para(d, "ENTERPRISE växte kraftigt tack vare SEAB (34,4 % av total omsättning FY26). SMB växte främst genom nya fastprisprojekt (SU-Produktionssystem, TR-Skogsportal, LM-Lärplattform).")
    save(d, fol / "kundsegmentering.docx")
    reg("DOC-CRM-010", "customers/kundsegmentering.docx", "RAPPORT",
        "Kundsegmentering och segmentanalys", "2026-09-15", "P-005",
        ["CUS-001", "CUS-002", "CUS-003", "CUS-004"],
        note="Offentlig omsättning minskade 21,7 % (KL-Vårdportal avslutad).")


# ---------------------------------------------------------------------------
# suppliers/
# ---------------------------------------------------------------------------

def section_suppliers(m: Model) -> None:
    fol = F["suppliers"]

    # ---- Leverantörsbedömningar ×8 ---------------------------------------------------
    bedom = [
        ("DOC-SUP-001", "leverantorsbedomning_cloudserve.docx", "Cloudserve Ireland Ltd", "2024-01-15",
         [("M365 + Azure", "Produktivitet och molnplattform")],
         [["Dataskydd", "DPA tecknat 2024-01-01; data inom EU (Irland)"],
          ["Moms", "Omvänd skattskyldighet (reverse charge) – leverantör utanför Sverige"],
          ["Drift", "SLA 99,9 %; exitmöjlighet via export"],
          ["Risknivå", "Låg – godkänd"]], "Godkänd"),
        ("DOC-SUP-002", "leverantorsbedomning_agila_verktyg.docx", "Agila Verktyg AB", "2023-03-10",
         [("Ärendehantering och wiki", "SaaS")],
         [["Dataskydd", "DPA tecknat 2023-02-01; data inom EU"],
          ["Risknivå", "Låg – godkänd"]], "Godkänd"),
        ("DOC-SUP-003", "leverantorsbedomning_designsuiten.docx", "Designsuiten AB", "2022-06-20",
         [("Designverktyg", "SaaS, 18 licenser varav 9 används")],
         [["Dataskydd", "DPA tecknat 2022-05-01"],
          ["Notering", "Låg utnyttjandegrad – ses över i licensinventeringen"],
          ["Risknivå", "Låg – godkänd"]], "Godkänd"),
        ("DOC-SUP-004", "leverantorsbedomning_pipeline_crm.docx", "Pipeline AB", "2022-12-01",
         [("CRM", "Innehåller personuppgifter om kunder och kontakter")],
         [["Dataskydd", "DPA tecknat 2022-12-01; data inom EU"],
          ["Notering", "DPA bör ses över vid nästa förnyelse (åldrat)"],
          ["Risknivå", "Medel – godkänd med anmärkning"]], "Godkänd med anmärkning"),
        ("DOC-SUP-005", "leverantorsbedomning_modellfabriken.docx", "Modellfabriken AB", "2025-02-10",
         [("AI-modell-API:er", "Användningen ökade kraftigt 2026 (AI-initiativet)")],
         [["Dataskydd", "DPA tecknat 2025-03-01; inga känsliga uppgifter får skickas"],
          ["Kostnad", "18 500 kr/mån – beställt av Daniel Nyström (systemägare)"],
          ["Risknivå", "Medel – godkänd med villkor"]], "Godkänd med villkor"),
        ("DOC-SUP-006", "leverantorsbedomning_analytics_cloud.docx", "Analytics Cloud Inc (USA)", "2025-04-28",
         [("Analysmolntjänst", "Personuppgifter överförs utanför EU/EES")],
         [["Tredjelandsöverföring", "SCC tecknade 2025-05-01"],
          ["Begränsning", "Känsliga personuppgifter får inte behandlas i tjänsten"],
          ["Risknivå", "Medel – godkänd med begränsning"]], "Godkänd med begränsning"),
        ("DOC-SUP-007", "leverantorsbedomning_datainsikt.docx", "Datainsikt AB", "2023-09-15",
         [("Analysverktyg", "10 licenser varav 2 används")],
         [["Dataskydd", "DPA tecknat 2023-09-01"],
          ["Notering", "Överlappar med Analytics Cloud; ses över i licensinventeringen"],
          ["Risknivå", "Låg – godkänd"]], "Godkänd"),
        ("DOC-SUP-008", "leverantorsbedomning_kraftkod.docx", "Kraftkod Konsult AB", "2025-01-20",
         [("Underkonsult – 2 utvecklare på SE-Billing", "Konsulttjänster")],
         [["Säkerhet", "Bakgrundskontroller utförda; NDA tecknat"],
          ["Kvalitet", "God leverans; kostnad 136 000 kr/mån under SE-Billing"],
          ["Risknivå", "Låg – godkänd"]], "Godkänd"),
    ]
    for doc_id, fname, sup, datum, rows_kv, fynd, status in bedom:
        d = new_doc()
        head(d, f"Säkerhetsbedömning av leverantör – {sup}", datum, "Jonas Sandberg, CTO", doc_id)
        table(d, ["Område", "Bedömning"], rows_kv)
        table(d, ["Fynd", "Kommentar"], fynd)
        kv(d, "Beslut", status)
        save(d, fol / fname)
        reg(doc_id, f"suppliers/{fname}", "RAPPORT",
            f"Säkerhetsbedömning leverantör – {sup}", datum, "P-002", ["ORG-NORDVIKEN"])
    # Nordhost (SUP-004) saknar medvetet bedömning (se systemförteckningen).

    # ---- Inköpsregister CSV (från leverantörsfakturorna i modellen) -----------------------
    from collections import defaultdict
    sup_name = {s.id: s.name for s in m.suppliers}
    sup_cat = {s.id: s.category for s in m.suppliers}
    fy26_tot = defaultdict(float)
    fy26_last = defaultdict(float)
    fy26_acct = {}
    for inv in m.supplier_invoices:
        dt_s = inv.get("date", "")
        if not dt_s:
            continue
        y, mo = int(dt_s[:4]), int(dt_s[5:7])
        if (2025, 10) <= (y, mo) <= (2026, 9):
            sid = inv.get("supplier_id", "?")
            net = float(inv.get("net") or 0)
            fy26_tot[sid] += net
            fy26_last[sid] = net
            fy26_acct[sid] = inv.get("account", "")
    ink_rows = []
    for sid in sorted(fy26_tot, key=lambda x: -fy26_tot[x]):
        ink_rows.append([sup_name.get(sid, sid), sup_cat.get(sid, ""), fy26_acct[sid],
                         f"{fy26_tot[sid]:.2f}", f"{fy26_last[sid]:.2f}"])
    csv_w(fol / "inkopsregister.csv",
          ["Leverantör", "Kategori", "Konto", "Totalt FY26 ex moms", "Månadsbelopp senaste månad"],
          ink_rows)
    reg("DOC-SUP-009", "suppliers/inkopsregister.csv", "REGISTER",
        "Inköpsregister FY26 (leverantörsfakturor)", "2026-10-10", "P-003",
        sorted(fy26_tot.keys()),
        note="Belopp ur ekonomisystemets leverantörsfakturor FY26; top-5: Kapellbacken, Pensionsvalet, Kraftkod, Cloudserve, Dataverket.")

    # ---- Systemförteckning -------------------------------------------------------------------
    d = new_doc()
    head(d, "Systemförteckning", "Uppdaterad 2026-09-20", "Jonas Sandberg, CTO", "DOC-SUP-010", "v2.3")
    table(d, ["System", "Leverantör", "Kritikalitet", "Systemägare", "Reservrutin"], [
        ["M365 / Azure", "Cloudserve Ireland", "Kritisk", "Jonas Sandberg", "Dokumenterad (offline-export)"],
        ["Hosting", "Nordhost AB", "Kritisk", "Jonas Sandberg", "SAKNAS"],
        ["Ärendehantering/wiki", "Agila Verktyg", "Medel", "Erik Norén", "Export till fil"],
        ["Chattverktyg", "Kanalen AB", "Låg", "Petra Wahlgren", "E-post"],
        ["Designverktyg", "Designsuiten AB", "Låg", "Johanna Sjöberg", "E-post"],
        ["VPN", "Säkra Nät AB", "Hög", "Jonas Sandberg", "Alternativ anslutning via MFA"],
        ["CRM", "Pipeline AB", "Medel", "Sara Holm", "SAKNAS"],
        ["Lönesystem", "Löneportalen AB", "Hög", "Anders Bergström", "Manuell beräkning (använd 2026-04)"],
        ["Ekonomisystem", "Företagssystem Nord", "Kritisk", "Anders Bergström", "Export + manuell bokföring"],
        ["AI-modell-API", "Modellfabriken AB", "Medel", "Daniel Nyström", "SAKNAS (beställare Daniel Nyström)"],
        ["Analysmolntjänst (USA)", "Analytics Cloud Inc", "Medel", "Daniel Nyström", "Datainsikt (delvis)"],
        ["Analysverktyg", "Datainsikt AB", "Låg", "Daniel Nyström", "Export till fil"],
        ["Samarbetsyta", "Whiteboard AB", "Låg", "Petra Wahlgren", "E-post"],
        ["CI/CD", "Bygglådan AB", "Hög", "Patrik Öberg", "Manuell deploy"],
        ["Monitoring", "Vakthuset AB", "Medel", "Simon Dahl", "Loggfilgranskning"],
        ["E-signatur", "Signera AB", "Låg", "Anders Bergström", "Papper"],
        ["Telefoni", "Telefonbolaget Väst", "Medel", "Petra Wahlgren", "Mobila abonnemang"],
        ["Dokumenthantering", "Arkivet AB", "Medel", "Petra Wahlgren", "Export till fil"],
        ["Backup", "Säkerhetskopian AB", "Kritisk", "Jonas Sandberg", "Sekundär kopia (testad 2025-11)"],
        ["HR-system", "Personalen AB", "Medel", "Petra Wahlgren", "Export till fil"],
    ])
    para(d, "Noteringar: (1) Säkerhetsbedömning saknas för Nordhost AB. (2) Reservrutin saknas för hosting, CRM och AI-API. (3) Behörighetsgenomgångar sker kvartalsvis enligt DOC-POL-008.")
    save(d, fol / "systemforteckning.docx")
    reg("DOC-SUP-010", "suppliers/systemforteckning.docx", "REGISTER",
        "Systemförteckning", "2026-09-20", "P-002",
        ["ORG-NORDVIKEN", "SUP-003", "SUP-004", "SUP-005", "SUP-009", "SUP-010", "SUP-011", "SUP-012", "SUP-013", "SUP-014"],
        version="2.3", note="Reservrutin saknas för Nordhost, Pipeline CRM och Modellfabriken. Bedömning saknas för Nordhost.")

    # ---- Licensutnyttjande ----------------------------------------------------------------------
    d = new_doc()
    head(d, "Licensutnyttjande-rapport", "Upprättad 2026-08-25", "Anders Bergström, CFO", "DOC-SUP-011", "v1.0")
    table(d, ["Verktyg", "Licenser köpta", "Licenser använda", "Kostnad/mån", "Kostnad outnyttjade/mån"], [
        ["Designsuiten", "18", "9", "11 200 kr", "5 600 kr"],
        ["Datainsikt", "10", "2", "7 800 kr", "6 240 kr"],
        ["M365", "30", "27", "95 000 kr (paket)", "–"],
        ["Whiteboard", "30", "24", "6 400 kr", "1 280 kr"],
    ])
    para(d, "Outnyttjade licenser i Designsuiten och Datainsikt kostar tillsammans cirka 11 840 kr per månad (cirka 142 000 kr per år). Förslag: säg upp 9 Designsuiten-licenser och 6 Datainsikt-licenser vid nästa förnyelsetillfälle.")
    para(d, "Metod: inloggningsstatistik från leverantörernas administrationsportaler, perioden maj–juli 2026. Användare med noll inloggningar under perioden räknas som outnyttjade.")
    save(d, fol / "licensutnyttjande_rapport.docx")
    reg("DOC-SUP-011", "suppliers/licensutnyttjande_rapport.docx", "RAPPORT",
        "Licensutnyttjande-rapport", "2026-08-25", "P-003",
        ["SUP-007", "SUP-014", "SUP-003", "SUP-015"],
        event_ids=["EVT-065"], note="Designsuiten 9/18, Datainsikt 2/10 använda.")

    # ---- Molnkostnadsrapport CSV (från 5420-strömmarna) -------------------------------------------
    saas = [s for s in m.streams if s.account == "5420"]
    months = sorted({k for s in saas for k in s.monthly_amount if (2025, 10) <= (int(k[:4]), int(k[5:7])) <= (2026, 9)})
    header = ["Tjänst", "Leverantör"] + months
    sup_name = {s.id: s.name for s in m.suppliers}
    moln_rows = []
    for s in sorted(saas, key=lambda x: x.id):
        row = [s.label, sup_name.get(s.supplier_id, s.supplier_id)]
        for k in months:
            row.append(f"{s.monthly_amount.get(k, 0):.2f}")
        moln_rows.append(row)
    tot_row = ["TOTALT", ""] + [f"{sum(s.monthly_amount.get(k, 0) for s in saas):.2f}" for k in months]
    moln_rows.append(tot_row)
    csv_w(fol / "molnkostnadsrapport.csv", header, moln_rows)
    reg("DOC-SUP-012", "suppliers/molnkostnadsrapport.csv", "REGISTER",
        "Molnkostnadsrapport (konto 5420, per månad)", "2026-10-10", "P-003",
        [s.supplier_id for s in saas],
        note="Månadssumman uppgår till 259 200 kr (2026-09). Källa: ekonomisystemets leverantörsströmmar.")

    # ---- Integrationslogg CSV -----------------------------------------------------------------------
    int_rows = [
        ["2025-11-18", "Lönesystem → Ekonomisystem", "FEL", "Felaktig avstämningsfil; manuell rättning (0,5 dag)", "Anders Bergström"],
        ["2026-01-22", "Lönesystem → Ekonomisystem", "FEL", "Saknade rader i överföringen; manuell komplettering (1 dag)", "Anders Bergström"],
        ["2026-02-28", "CRM → Ekonomisystem", "OK", "–", "Anders Bergström"],
        ["2026-03-05", "CRM → Ekonomisystem", "FEL", "Dubblerade fakturaunderlag; rättning samma dag", "Anders Bergström"],
        ["2026-04-20", "Lönesystem → Ekonomisystem", "HAVERI", "Tredje felet på 6 månader; manuell överföring tog 2 dagar (se DOC-IT-001)", "Anders Bergström"],
        ["2026-05-28", "Lönesystem → Ekonomisystem", "OK", "Efter leverantörspatch", "Anders Bergström"],
        ["2026-06-30", "Tidrapporter → Ekonomisystem", "OK", "–", "Anders Bergström"],
        ["2026-09-14", "Lönesystem → Ekonomisystem", "FEL", "Felmatchade kostnadsställen; manuell rättning (0,5 dag)", "Anders Bergström"],
    ]
    csv_w(fol / "integrationslogg.csv",
          ["Datum", "Integration", "Status", "Kommentar", "Rapporterad av"], int_rows)
    reg("DOC-SUP-013", "suppliers/integrationslogg.csv", "REGISTER",
        "Integrationslogg", "2026-10-10", "P-002", ["SUP-010", "SUP-011", "SUP-009"],
        note="Lönesystem → Ekonomisystem har felat upprepade gånger (2025-11-18, 2026-01-22, 2026-04-20 haveri).")

    # ---- Behörighetsmatris CSV ------------------------------------------------------------------------
    bh_rows = [
        ["Maja Lindqvist", "VD", "M365: användare; Ekonomi: läs; CRM: läs", "OK"],
        ["Jonas Sandberg", "CTO", "M365: global admin; Azure: admin; VPN: admin", "OK"],
        ["Anders Bergström", "CFO", "Ekonomi: admin; Lönesystem: admin; Bank: behörig", "OK"],
        ["Petra Wahlgren", "HR/kontor", "HR: admin; CRM: admin; M365: användare; Ekonomi: behörighetsattest", "ÖVERDRIVEN – har attestroll i ekonomisystemet utan att ingå i ekonomi"],
        ["Sara Holm", "Försäljning", "CRM: användare (läs/skriv); M365: användare", "OK"],
        ["Lisa Sundberg", "Marknad", "CRM: användare; Designsuiten: admin", "OK"],
        ["Erik Norén", "Leverans", "CRM: läs; Ärendehantering: admin", "OK"],
        ["David Ekström", "Projektledare", "M365: GLOBAL ADMIN; Ekonomi: läs; Ärendehantering: admin", "ÖVERDRIVEN – global admin utan IT-roll"],
        ["Karin Olsson", "Projektledare", "Ärendehantering: användare; M365: användare", "OK"],
        ["Tomas Berg", "Arkitekt", "Azure: admin; M365: användare", "OK"],
        ["Daniel Nyström", "Data/AI", "Analysmolntjänst: admin; Datainsikt: admin; Modellfabriken: admin", "OK"],
        ["Patrik Öberg", "DevOps", "CI/CD: admin; Monitoring: admin; M365: användare", "OK"],
        ["Simon Dahl", "DevOps", "CI/CD: admin; Monitoring: användare", "OK"],
        ["Maria Gustavsson", "Testledare", "Testverktyg: admin; Ärendehantering: användare", "OK"],
        ["Johanna Sjöberg", "UX", "Designsuiten: användare; M365: användare", "OK"],
        ["Björn Falk (avgången 2026-08-31)", "Utvecklare", "M365: användare; Ärendehantering: användare – KONTO AKTIVT", "AVVIKELSE – konto inte avslutat"],
        ["Klara Månsson (avgången 2026-09-30)", "Support", "Ärendehantering: admin; M365: användare", "AVSLUTAS 2026-10-15"],
    ]
    csv_w(fol / "behorighetsmatris.csv",
          ["Användare", "Roll", "Behörigheter", "Anmärkning"], bh_rows)
    reg("DOC-SUP-014", "suppliers/behorighetsmatris.csv", "REGISTER",
        "Behörighetsmatris", "2026-10-08", "P-002", ["ORG-NORDVIKEN"],
        note="Minst två användare med överdrivna behörigheter; ett avgånget konto fortfarande aktivt.")

    # ---- Säkerhetsincidentlogg CSV ---------------------------------------------------------------------
    sec_rows = [
        ["2024-10-15", "Phishing till ekonomiavdelningen", "Medel", "Två medarbetare klickade; lösenord återställda; inget konstaterat dataintrång (DOC-SEC-001)", "Stängd"],
        ["2025-03-22", "Misstänkta inloggningsförsök mot M365", "Låg", "Blockerat av MFA; konton granskade", "Stängd"],
        ["2026-01-18", "MFA-trötthetsattacker (push-spam)", "Låg", "Utbildningsinsats; nummermatchning aktiverad", "Stängd"],
        ["2026-08-04", "Driftstörning Nordhost (6 h)", "Hög", "Ej säkerhetsrelaterad men inkluderad p.g.a. kundpåverkan (DOC-IT-002)", "Stängd"],
        ["2026-09-02", "AI-svar utan källstöd i kundrapporter", "Medel", "Rapporter korrigerade; loggning saknades (DOC-IT-003)", "Åtgärd pågår"],
        ["2026-09-28", "Credential stuffing-försök mot CRM-inloggning", "Medel", "Ingen åtkomst konstaterad; MFA höll; IP-blockering införd", "Öppen"],
    ]
    csv_w(fol / "sakerhetsincidentlogg.csv",
          ["Datum", "Incident", "Allvarlighetsgrad", "Beskrivning/åtgärd", "Status"], sec_rows)
    reg("DOC-SUP-015", "suppliers/sakerhetsincidentlogg.csv", "REGISTER",
        "Säkerhetsincidentlogg", "2026-10-08", "P-002", ["ORG-NORDVIKEN"],
        note="Senaste incidenten: credential stuffing 2026-09-28 (öppen).")

    # ---- DR/BCP-plan ------------------------------------------------------------------------------------
    d = new_doc()
    head(d, "DR/BCP-plan (återställningsplan)", "Fastställd 2024-11-08, reviderad 2025-05-20",
         "Jonas Sandberg, CTO", "DOC-SUP-016", "v1.1")
    table(d, ["Mål", "Värde"], [
        ["RTO (återställningstid)", "48 timmar"],
        ["RPO (dataförlusttolerans)", "24 timmar"],
        ["Maximalt acceptabelt avbrott (kritisk drift)", "48 timmar"],
        ["Backupfrekvens", "Dagligen (Säkerhetskopian AB)"],
    ])
    para(d, "Scenarier: totalt avbrott hos hostingleverantören (Nordhost), avbrott i M365/Azure, bortfall av kontorslokal, förlust av nyckelpersonal.")
    para(d, "Kritisk ordning: 1) hosting + backup, 2) M365/Azure, 3) ekonomisystem, 4) CRM.")
    para(d, "Ansvariga: Jonas Sandberg (IT), Anders Bergström (ekonomi), Petra Wahlgren (kommunikation).")
    para(d, "Test: planen testades senast 2024-11-14. Nästa test var planerat till våren 2026 men sköts upp; nytt datum sätts i samband med översynen av reservrutiner (se DOC-SUP-018).")
    save(d, fol / "dr_bcp_plan.docx")
    reg("DOC-SUP-016", "suppliers/dr_bcp_plan.docx", "PLAN",
        "DR/BCP-plan", "2025-05-20", "P-002", ["ORG-NORDVIKEN", "SUP-004", "SUP-021"],
        version="1.1", note="RTO 48 h, RPO 24 h. Senast testad 2024-11-14.")

    # ---- Försäkringsbrev ------------------------------------------------------------------------------------
    d = new_doc()
    head(d, "Försäkringsbrev – Företagsförsäkring", "Försäkringsperiod 2026-01-01 – 2026-12-31",
         "Tryggast Försäkring AB", "DOC-SUP-017", "v1.0")
    kv(d, "Försäkringstagare", "Nordviken Digital AB, org.nr 559245-1673")
    kv(d, "Försäkringsgivare", "Tryggast Försäkring AB")
    kv(d, "Premie", "21 000 kr/månad")
    table(d, ["Moment", "Försäkringsbelopp / villkor"], [
        ["Ansvarsförsäkring (företag)", "10 000 000 kr (tak per skada och år)"],
        ["Egendomsförsäkring", "5 000 000 kr (lös egendom, inbrott, brand, vatten)"],
        ["Rättsskyddsförsäkring", "2 000 000 kr"],
        ["Olycksfallsförsäkring tjänsteresa", "10 prisbasbelopp vid invaliditet"],
        ["Förmögenhetsbrottsförsäkring", "1 000 000 kr"],
    ])
    para(d, "Självrisk: 20 000 kr (ansvar), 10 000 kr (egendom).")
    para(d, "Vid skada: kontakta Tryggast Försäkring AB, skadeavdelningen, tel. 08-555 010 00.")
    save(d, fol / "forsakringsbrev.docx")
    reg("DOC-SUP-017", "suppliers/forsakringsbrev.docx", "BREV",
        "Försäkringsbrev företagsförsäkring", "2026-01-01", "SYSTEM",
        ["ORG-NORDVIKEN", "SUP-038"], valid_from="2026-01-01", valid_to="2026-12-31",
        note="Ansvar 10 MSEK, egendom 5 MSEK. Cyber-/avbrottsförsäkring saknas.")

    # ---- Reservrutinsförteckning ------------------------------------------------------------------------------
    d = new_doc()
    head(d, "Reservrutinsförteckning", "Uppdaterad 2026-09-20", "Jonas Sandberg, CTO", "DOC-SUP-018", "v1.2")
    table(d, ["System/tjänst", "Reservrutin", "Testad senast"], [
        ["Hosting (Nordhost)", "SAKNAS", "–"],
        ["M365 / Azure", "Offline-export + mobila klienter", "2025-11-14"],
        ["Ekonomisystem", "Export + manuell bokföring", "2026-04-20 (använd i skarpt läge)"],
        ["Lönesystem", "Manuell beräkning i kalkylark", "2026-04-20 (använd i skarpt läge)"],
        ["CRM (Pipeline)", "SAKNAS (export manuellt 1 gång/mån)", "2026-06-30"],
        ["Backup", "Sekundär kopia hos Säkerhetskopian", "2025-11-14"],
        ["Telefoni", "Mobila abonnemang", "2026-01-15"],
        ["AI-modell-API (Modellfabriken)", "SAKNAS", "–"],
        ["E-signatur", "Papperssignering", "2025-06-10"],
    ])
    para(d, "Åtgärd: reservrutin för hosting ska tas fram i samband med SLA-förhandlingen med Nordhost (efter driftstörningen 2026-08-04).")
    save(d, fol / "reservrutiner.docx")
    reg("DOC-SUP-018", "suppliers/reservrutiner.docx", "REGISTER",
        "Reservrutinsförteckning", "2026-09-20", "P-002",
        ["ORG-NORDVIKEN", "SUP-004", "SUP-009", "SUP-012"], version="1.2",
        note="Reservrutin saknas för hosting, CRM och AI-API.")

    # ---- DOC-SEC-001 Phishingincident -----------------------------------------------------------------------------
    d = new_doc()
    head(d, "Incidentrapport – phishing till ekonomiavdelningen", "2024-10-15",
         "Jonas Sandberg, CTO", "DOC-SEC-001", "v1.0")
    kv(d, "Incidenttyp", "Nätfiske (phishing) via e-post")
    kv(d, "Upptäckt", "2024-10-15 kl. 09:40")
    kv(d, "Omfattning", "Två medarbetare på ekonomiavdelningen klickade på länken och angav lösenord")
    para(d, "")
    para(d, "Händelseförlopp: Ett mejl utgav sig för att komma från 'Microsoft 365-teamet' med begäran om lösenordsverifiering. Två medarbetare följde länken. Inget konstaterat dataintrång – MFA blockerade inloggningsförsöken.")
    para(d, "Vidtagna åtgärder:")
    table(d, ["Åtgärd", "Ansvarig", "Klart"], [
        ["Återställning av lösenord för berörda konton", "Jonas Sandberg", "2024-10-15"],
        ["Granskning av inloggningsloggar 14 dagar bakåt", "Jonas Sandberg", "2024-10-16"],
        ["Säkerhetsgenomgång för ekonomiavdelningen", "Jonas Sandberg", "2024-10-22"],
        ["Utbildningsinsats för hela bolaget", "Petra Wahlgren", "2024-11-15"],
    ])
    para(d, "Slutsats: Inget dataintrång konstaterades. Medvetenheten kring nätfiske behöver stärkas (årlig utbildning införs).")
    save(d, fol / "incidentrapport_phishing_2024-10-15.docx")
    reg("DOC-SEC-001", "suppliers/incidentrapport_phishing_2024-10-15.docx", "INCIDENT",
        "Incidentrapport phishing 2024-10-15", "2024-10-15", "P-002",
        ["ORG-NORDVIKEN"], event_ids=["EVT-002"])

    # ---- DOC-IT-001 Integrationshaveri -----------------------------------------------------------------------------
    d = new_doc()
    head(d, "Incidentrapport – integrationshaveri lönesystem → ekonomisystem", "2026-04-20",
         "Jonas Sandberg, CTO", "DOC-IT-001", "v1.0")
    kv(d, "Incident", "Integrationen Löneportalen → Företagssystem Nord fallerade")
    kv(d, "Tidpunkt", "2026-04-20, lönekörningens överföring misslyckades")
    kv(d, "Förekomst", "Tredje gången på 6 månader (tidigare: 2025-11-18, 2026-01-22)")
    para(d, "")
    para(d, "Förlopp: Överföringen av april-lönekörningen misslyckades helt. Manuell överföring av lönetransaktioner till ekonomisystemet tog 2 arbetsdagar (Anders Bergström).")
    para(d, "Rotorsak: Löneportalen ändrade API-schemat i en uppdatering utan att informera oss; vår integration var inte versionshanterad.")
    para(d, "Åtgärder:")
    table(d, ["Åtgärd", "Ansvarig", "Klart senast"], [
        ["Versionspinning av integrationen + felhantering", "Jonas Sandberg", "2026-05-15"],
        ["Övervakning av integrationskörningar (Vakthuset)", "Simon Dahl", "2026-05-31"],
        ["Krav mot Löneportalen på ändringsavisering 30 dagar i förväg", "Anders Bergström", "2026-05-08"],
        ["Dokumenterad manuell reservrutin", "Anders Bergström", "Klar (använd i skarpt läge)"],
    ])
    save(d, fol / "incidentrapport_integration_2026-04-20.docx")
    reg("DOC-IT-001", "suppliers/incidentrapport_integration_2026-04-20.docx", "INCIDENT",
        "Incidentrapport integrationshaveri lönesystem", "2026-04-20", "P-002",
        ["SUP-010", "SUP-011"], event_ids=["EVT-056"],
        note="Tredje felet på 6 månader; manuell överföring tog 2 dagar.")

    # ---- DOC-IT-002 Driftstörning Nordhost ----------------------------------------------------------------------------
    d = new_doc()
    head(d, "Incidentrapport – driftstörning hos Nordhost", "2026-08-04",
         "Jonas Sandberg, CTO", "DOC-IT-002", "v1.0")
    kv(d, "Incident", "Hostingplattformen (Nordhost AB) låg nere i 6 timmar")
    kv(d, "Tid", "2026-08-04 kl. 08:14 – 14:22")
    kv(d, "Orsak", "Fel i Nordhosts nätverksutrustning vid schemalagt underhåll (enligt Nordhost)")
    para(d, "")
    para(d, "Påverkan: förvaltningskunder med drift hos Nordhost påverkades – SE-Förvaltning (SEAB), NH-Förvaltning (Norrhamns Hamn) och FS-Förvaltning (Fyrstadens kommun). Inga data gick förlorade (backup återställdes).")
    para(d, "SLA: avtalet anger 99,9 % tillgänglighet. SLA-ersättning diskuteras med Nordhost (kreditering av månadsavgiften).")
    para(d, "Brister: reservrutin för hosting saknas (se DOC-SUP-018). Kundkommunikationen kom igång först efter 3 timmar.")
    para(d, "Åtgärder: (1) SLA-förhandling med Nordhost, (2) reservrutin för hosting, (3) kommunikationsplan för driftstörningar.")
    save(d, fol / "incidentrapport_nordhost_2026-08-04.docx")
    reg("DOC-IT-002", "suppliers/incidentrapport_nordhost_2026-08-04.docx", "INCIDENT",
        "Incidentrapport driftstörning Nordhost", "2026-08-04", "P-002",
        ["SUP-004", "CUS-001", "CUS-011", "CUS-003"], event_ids=["EVT-064"],
        note="6 timmars avbrott; SLA-ersättning diskuteras; reservrutin saknas.")

    # ---- DOC-IT-003 AI-svar utan källstöd ---------------------------------------------------------------------------------
    d = new_doc()
    head(d, "Incidentrapport – AI-svar utan källstöd i kundrapporter", "2026-09-02",
         "Daniel Nyström, Data/AI-specialist", "DOC-IT-003", "v1.0")
    kv(d, "Incident", "Det interna AI-verktyget levererade svar utan verifierbart källstöd i två kundrapporter")
    kv(d, "Upptäckt", "2026-09-02 vid granskning inför leverans")
    para(d, "")
    para(d, "Berörda leveranser: KPI-rapport till Gruvbergets Mineral (GM-Bergdatasystem) samt en intern sammanställning. Siffrorna stämde inte med underliggande data och korrigerades manuellt före utskick.")
    para(d, "Rotorsak: verktyget svarade på frågor utanför sitt underlag i stället för att returnera 'inga data'. Loggning av AI-användningen saknades, vilket försvårade spårningen (AI-policyns loggningskrav var inte implementerat).")
    para(d, "Åtgärder:")
    table(d, ["Åtgärd", "Ansvarig", "Klart senast"], [
        ["Implementera loggning av AI-användning", "Daniel Nyström", "2026-09-30"],
        ["Källhänvisningskontroll i rapportmallen", "Daniel Nyström", "2026-09-15"],
        ["Genomgång av policyn med alla användare", "Petra Wahlgren", "2026-10-15"],
    ])
    save(d, fol / "incidentrapport_ai_kallstod_2026-09-02.docx")
    reg("DOC-IT-003", "suppliers/incidentrapport_ai_kallstod_2026-09-02.docx", "INCIDENT",
        "Incidentrapport AI-svar utan källstöd", "2026-09-02", "P-026",
        ["PRJ-091", "SUP-012", "CUS-013"], event_ids=["EVT-066"],
        note="Två kundrapporter korrigerade; loggning saknades.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    m = Model().load(str(ROOT / "ground_truth" / "truth_model.json"))
    MANIFEST.clear()
    section_company(m)
    section_policies(m)
    section_management(m)
    section_correspondence(m)
    section_projects(m)
    section_employees(m)
    section_customers(m)
    section_suppliers(m)
    # manifest
    out = ROOT / "generator" / "data" / "operations_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(MANIFEST, fh, ensure_ascii=False, indent=2)
    print(f"operations.py: {len(MANIFEST)} manifestposter skrivna till {out}")


if __name__ == "__main__":
    main()
