# Spec: Modulmotor — manifest, registry, DB-backade sub-frågor, Spinndoktor-komponentdelning

Kontext: plattformen har idag två moduler (politik-simulering, DD) som delar kärninfrastruktur
(Kund/Projekt-scoping, Persona-modell, run/trace, Expertpanel-motor, Spinndoktor) men kopplas
ihop manuellt per modul. Målet är ett explicit modulkontrakt så att en tredje modul (t.ex.
offentlig upphandling) kan återanvända DD:s mönster utan att kopiera kod, och så att
delade komponenter (personas, intervju, panel-motor, Spinndoktor) exponeras deklarativt
istället för via if/else på `report.mode` / hårdkodade importer.

Bygg i fyra faser, i ordning. Varje fas ska vara körbar och testbar innan nästa påbörjas.
Inga befintliga endpoints eller DB-rader får gå sönder under migreringen — allt är additivt
tills sista steget i respektive fas där gammal statisk kod tas bort.

---

## Fas 1 — Modulmanifest + registry (ingen befintlig kod flyttas)

### 1.1 Manifest-dataclass

Ny fil: `backend/app/modules/manifest.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fastapi import APIRouter


@dataclass(frozen=True)
class SpindoctorBinding:
    """Per-modul koppling in i Spinndoktor-lagret."""
    context_builder: Callable[..., str]  # samma signatur som build_dd_spindoctor_context_block
    mcp_tool_names: frozenset[str] = field(default_factory=frozenset)
    supports_interview: bool = False


@dataclass(frozen=True)
class ModuleManifest:
    id: str                        # "dd", "politik", framtida "upphandling"
    name: str                      # visningsnamn i GUI
    icon: str                      # emoji eller ikon-key, för nav
    router: APIRouter              # monteras på /api/{id}
    prompt_namespace: str          # Configuration.prompts[namespace]
    frontend_entry: str            # frontend route-namespace, t.ex. "dd"
    components: frozenset[str] = field(default_factory=frozenset)
    # kända components: "personas", "interview", "panel_engine", "spindoctor"
    sub_questions_provider: Callable[[], list] | None = None
    expert_defaults_provider: Callable[[], list] | None = None
    spindoctor: SpindoctorBinding | None = None
```

Håll den fri från affärslogik — bara deklaration + referenser till redan existerande callables.

### 1.2 Registry

Ny fil: `backend/app/modules/registry.py`

```python
from app.modules.manifest import ModuleManifest
from app.api.dd import router as dd_router
# ... importera politik-routrar som redan monteras i main.py idag

MODULE_REGISTRY: dict[str, ModuleManifest] = {
    "dd": ModuleManifest(
        id="dd",
        name="Due Diligence",
        icon="🔍",
        router=dd_router,
        prompt_namespace="dd",
        frontend_entry="dd",
        components=frozenset({"personas", "panel_engine", "spindoctor"}),
        # providers och spindoctor-binding kopplas in i Fas 2 och Fas 3
    ),
    "politik": ModuleManifest(
        id="politik",
        name="Politisk simulering",
        icon="🗳️",
        router=...,  # identifiera rätt befintlig router/routrar för politik-flödet
        prompt_namespace="politik",
        frontend_entry="politik",
        components=frozenset({"personas", "interview", "spindoctor"}),
    ),
}
```

**Observera:** `DdCampaign.module` (default `"dd"`) och `PanelSession.protocol` (default
`"generic_panel"`) finns redan i `backend/app/database/models.py` — inga migrations behövs
för att modul-id:t ska existera i datan, bara för att koppla ihop det med registryn.

### 1.3 main.py-loop

I `backend/app/main.py`: byt manuell `app.include_router(dd.router)` /motsvarande politik-rader
mot en loop över `MODULE_REGISTRY`:

```python
from app.modules.registry import MODULE_REGISTRY

for module in MODULE_REGISTRY.values():
    app.include_router(module.router, prefix=f"/api/{module.id}")
```

Kontrollera faktiska nuvarande prefix i `backend/app/api/dd.py` och motsvarande politik-router
innan bytet — om prefix redan sätts inne i respektive `APIRouter(prefix=...)` ska prefixet INTE
sättas dubbelt här. Om det redan finns, hoppa över `prefix=` i loopen och behåll det router-interna.

### 1.4 Acceptanskriterium fas 1

- Alla befintliga endpoints svarar identiskt (samma URL:er som innan).
- `MODULE_REGISTRY` är den enda källan `main.py` läser för routermontering.
- Ingen befintlig fil i `services/dd/`, `services/panel/`, `services/spindoctor_*` har flyttats
  eller ändrats ännu.

---

## Fas 2 — Sub-frågor och expertprofiler till databasen, modul-skopat

Mönster: kopiera strukturen från `services/catalog_store.py` (`CatalogList`-modellen) —
global default-rad seedas från statisk Python, redigerbar i DB därefter.

### 2.1 Ny tabell: `PanelSubQuestion`

I `backend/app/database/models.py`:

```python
class PanelSubQuestion(Base):
    """Modul-skopade bedömningsdimensioner för Expertpanel-motorn."""
    __tablename__ = "panel_sub_questions"
    __table_args__ = (
        UniqueConstraint("module", "key", name="uq_panel_sub_questions_module_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
```

**Droppa `expert_label`-fältet helt** — bär inte över det från `DdSubQuestion`. Det är död
metadata sedan raise-hand-mekanismen infördes (experter räcker upp handen, äger inte statiskt
en sub-fråga).

Alembic-migration (eller motsvarande) för ny tabell. Ingen ändring av befintliga tabeller.

### 2.2 Ny tabell: `PanelExpertProfile` (motsvarande för `default_experts.py`)

Läs `backend/app/services/dd/default_experts.py` och `expert_roles.py` innan du designar
kolumnerna — matcha den faktiska datastrukturen där (troligen namn, kompetensområde, prompt-
mall/persona-attribut) snarare än att gissa schema här. Följ samma `module`-skopade mönster
som `PanelSubQuestion`.

### 2.3 Store-modul

Ny fil: `backend/app/services/panel/sub_questions_store.py` (och motsvarande för expertprofiler),
med samma tre funktioner som `catalog_store.py` har för `CatalogList`:

- `get_sub_questions(session, module: str) -> list[PanelSubQuestion]`
- `ensure_sub_question_defaults(session, module: str, defaults: list[...]) -> int` — fyller på
  saknade nycklar, rör inte redan redigerade rader (samma logik som
  `ensure_catalog_defaults`)
- CRUD för att redigera/inaktivera i GUI senare (räcker med get/ensure i denna fas — CRUD-
  endpoints är separat GUI-arbete, inte del av detta spec)

### 2.4 Koppla in i manifestet

I `registry.py`: DD:s manifest får

```python
sub_questions_provider=lambda: DD_SUB_QUESTION_DEFAULTS,  # de gamla statiska defaultsen, nu bara seed-data
```

`DD_SUB_QUESTION_DEFAULTS` är den gamla tupeln från `sub_questions.py`, omdöpt och nedgraderad
till ren seed-data (utan `expert_label`). Vid app-start eller migrationskörning: loopa
`MODULE_REGISTRY`, kör `ensure_sub_question_defaults(session, module.id, module.sub_questions_provider())`
för varje modul som har en provider.

### 2.5 Byt ut läsningen i DD-panelen

Hitta alla ställen som importerar `DD_SUB_QUESTIONS` eller `sub_question_by_id` (troligast i
`services/dd/`, `services/panel/dd_engine.py`, `services/spindoctor_dd.py`) och byt mot
DB-läsning via store-modulen, skopat på `module="dd"`. `spindoctor_dd.py`s
`average_scores_by_sub_question()` itererar idag över `DD_SUB_QUESTIONS` — den ska istället
ta en `list[PanelSubQuestion]` som redan hämtats, inte importera konstanten direkt.

### 2.6 Acceptanskriterium fas 2

- `sub_questions.py` och `default_experts.py` innehåller bara ren seed-data (dataclasses/dicts),
  ingen kod läser dem direkt längre utanför store-modulens seed-funktion.
- Befintliga DD-körningar/rapporter renderar identiskt (samma sub-frågor, samma ordning).
- Går att lägga till en ny sub-fråga för `module="dd"` via DB-insert utan kodändring och se
  den dyka upp i nästa panel-körning.

---

## Fas 3 — Spinndoktor: filtrera verktyg per modul, formalisera context_builder

### 3.1 Bakgrund (för Cursor att förstå varför)

`spindoctor_context.py::build_spindoctor_context()` grenar redan korrekt på `report.mode`
mellan politik-kontext (inline) och `spindoctor_dd.py::build_dd_spindoctor_context_block()`.
Den delen ändras minimalt — bara att grenen ska slå upp `MODULE_REGISTRY[module_id].spindoctor.context_builder`
istället för hårdkodad if/else.

`spindoctor_mcp_tools.py::spindoctor_mcp_tool_specs()` gör däremot INGEN uppdelning — den
returnerar unionen av alla verktyg (DD:s `company_mcp`-verktyg, `get_report_dd`, `get_report_ssr`,
intervju-verktyg, SCB-verktyg, sökverktyg) oavsett vilken rapport chattsessionen gäller.
Korrekthet säkerställs idag runtime i `_resolve_bundles()` som kastar fel om intervju-verktyg
anropas på en DD-rapport. Det ska bytas mot att verktygen helt enkelt inte exponeras för fel
modul, snarare än att nekas vid anropstillfället.

### 3.2 SpindoctorBinding per modul

I `registry.py`, komplettera manifesten:

```python
"dd": ModuleManifest(
    ...,
    spindoctor=SpindoctorBinding(
        context_builder=build_dd_spindoctor_context_block,
        mcp_tool_names=frozenset({"get_report_dd"}) | COMPANY_TOOL_NAMES,
        supports_interview=False,
    ),
),
"politik": ModuleManifest(
    ...,
    spindoctor=SpindoctorBinding(
        context_builder=build_politik_spindoctor_context_block,  # bryt ut nuvarande inline-kod
        mcp_tool_names=frozenset({"get_report_ssr"}),
        supports_interview=True,
    ),
),
```

Bryt ut den nuvarande inline-koden för politik-kontext i `build_spindoctor_context()` till en
egen namngiven funktion `build_politik_spindoctor_context_block()` i en lämplig fil (t.ex.
`spindoctor_politik.py`, spegling av `spindoctor_dd.py`) — rör inte logiken, bara flytta den
till en fristående funktion så den kan refereras från manifestet.

### 3.3 Filtrera verktygsexponering

I `spindoctor_mcp_tools.py`:

- `spindoctor_mcp_tool_specs()` tar en `module_id: str`-parameter, slår upp
  `MODULE_REGISTRY[module_id].spindoctor.mcp_tool_names` och filtrerar de fasta specs-listorna
  (`_widget_tool_specs()`, `_list_tool_specs()`, etc.) så bara verktyg vars namn finns i
  bindingens `mcp_tool_names`, plus alltid-tillgängliga generiska verktyg (`render_chart`,
  `place_note`, `list_runs`/`list_reports`/`list_populations`), returneras.
- Intervju-verktygen (`_INTERVIEW_TOOL_NAMES`, `_READ_INTERVIEW_TOOL_NAMES`,
  `start_interview` i `_WIDGET_TOOL_NAMES`) inkluderas bara om `binding.supports_interview`
  är sant för aktuell modul.
- `run_spindoctor_mcp_tool()` behöver `module_id` för samma filtrering vid anrop — returnera
  tydligt fel om ett verktygsnamn anropas som inte hör till modulen, hellre än att låta det nå
  `_resolve_bundles()`s runtime-koll (den kollen får gärna vara kvar som extra säkerhetsnät,
  men ska inte vara den enda spärren).
- `module_id` härleds från `ctx.report_id` → `Report.mode` (finns redan i `Report`-modellen)
  vid start av chattsessionen, en gång, inte per verktygsanrop.

### 3.4 Acceptanskriterium fas 3

- En DD-chattsession kan inte längre anropa `start_interview`/`ask_interview_question`
  överhuvudtaget (verktyget syns inte i tool specs), istället för att kastas som runtime-fel.
- En politik-chattsession ser inte `get_report_dd` eller company-verktygen i sin toolset.
- Befintliga DD- och politik-Spinndoktor-flöden fungerar identiskt för operatören i övrigt
  (samma svar, samma widgets) — bara den dolda verktygsytan minskar.

---

## Fas 4 (uppföljning, ej del av detta spec-batch)

- Frontend: `frontend/src/modules/<id>/manifest.ts` + `moduleRegistry.ts`, kopplat till Kundens
  `tillgängliga_moduler`.
- Kampanj-nivå `modul`-fält generaliserat bortom `DdCampaign.module` om fler moduler behöver
  kampanj-typning utanför DD.
- CRUD-GUI för `PanelSubQuestion`/`PanelExpertProfile` (redigera i UI, inte bara DB-insert).

Vänta med Fas 4 tills Fas 1–3 är granskade och i produktion.

---

## PR-ordning för Cursor

Skicka som separata PR:er i denna ordning, en i taget, vänta på granskning innan nästa:

1. Fas 1: manifest + registry + main.py-loop (noll beteendeförändring)
2. Fas 2.1–2.3: nya tabeller + store-moduler (additivt, inget befintligt kopplas om än)
3. Fas 2.4–2.6: koppla in providers + byt ut läsningar (här blir DD faktiskt DB-driven)
4. Fas 3: Spinndoktor-binding + verktygsfiltrering

Varje PR ska vara körbar och testbar isolerat. Inga PR:er slår ihop flera faser.