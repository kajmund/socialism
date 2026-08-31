# Spec: Modulmotor Fas 4 — frontend-registry, kundens moduler, panelkatalog-GUI

Förutsättning: Fas 1–3 är i produktion (manifest + registry, DB-backade sub-frågor/expertprofiler,
Spinndoktor-binding). Fas 4 kopplar ihop det deklarativa kontraktet med GUI och kundscoping.

Inga befintliga endpoints eller DB-rader får gå sönder — allt är additivt. Tabellen
`dd_campaigns` behåller namnet; `module` är diskriminatorn för kampanj-typning.

---

## 4.1 Frontend-manifest + registry

Nya filer:

```text
frontend/src/modules/manifest.ts          # ModuleManifest-typ + kända component-id:n
frontend/src/modules/dd/manifest.ts
frontend/src/modules/politik/manifest.ts
frontend/src/modules/moduleRegistry.ts    # MODULE_REGISTRY, helpers
```

Manifestet speglar backendens deklaration (id, icon, frontend_entry, components) men utan
routrar/callables. Visningsnamn går via i18n (`modules.<id>.name`).

Kända `components` (samma som backend, plus `campaigns`):

- `personas`
- `interview`
- `panel_engine`
- `spindoctor`
- `campaigns` — modulen äger kampanj-ytan (DD idag)

`MODULE_REGISTRY` är den enda källan frontend läser för “vilka moduler finns”. Nav, rapportflikar
och kampanjlistning slår upp här — inte via hårdkodade `"dd"` / `"politik"`-listor.

---

## 4.2 Kundens `available_modules`

Ny kolumn på `Kund`:

```python
available_modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
```

Lista av modul-id:n från `MODULE_REGISTRY`. Alembic-migration (additiv). Seed:

| slug         | available_modules |
|--------------|-------------------|
| `devbrains`  | `["politik"]`     |
| `bolag-demo` | `["dd"]`          |

`ensure_default_kunder` sätter värdet vid **insert**. Befintliga rader backfillas en gång i
migrationen. Tom lista efter admin-redigering skrivs inte över vid startup.

API:

- `GET /kunder` / `GET /kunder/{id}` inkluderar `available_modules`
- `PATCH /kunder/{id}` med `{ "available_modules": ["politik", "dd"] }`
  - Okänt modul-id → 400 (ingen tyst filtrering)
  - Dubbletter tas bort, ordning bevaras

`GET /modules` returnerar serialiserade manifests (id, name, icon, frontend_entry, components)
så admin-GUI:t kan visa giltiga id:n utan att duplicera backendnamn.

Frontend: `useKundModules()` hämtar kunder, filtrerar på inloggningens tenant (bolag →
`bolag-demo`, OS-användare → `devbrains`, admin → union av alla) och returnerar manifests
vars id finns i `available_modules`. Rapportflikar och bolag-nav använder den listan — inte
`AuthUser.modules` (kvar som statisk inloggningshint).

---

## 4.3 Kampanj-nivå `module`

`DdCampaign.module` är redan diskriminatorn. Generalisera kontraktet, byt inte tabellnamn:

- Backend: `components` för DD inkluderar `"campaigns"`.
- `POST /dd/campaigns` avvisar `module` som inte finns i registry eller saknar `campaigns`.
- Frontend: kampanjlista/skapande tar modul-id från registry (`modulesWith("campaigns")`),
  inte en hårdkodad `"dd"`-sträng i anropet.
- Befintliga URL:er (`/dd/campaigns`, `/bolag/campaigns`) oförändrade.

En tredje modul som ska ha kampanjer lägger `"campaigns"` i sitt manifest och skickar sitt id
vid create — samma tabell, samma API.

---

## 4.4 CRUD-GUI för `PanelSubQuestion` / `PanelExpertProfile`

Store-modulerna (Fas 2) utökas med create/update (ingen hård delete — inaktivera via `active`).

API under `/panel` (admin, samma yta som övriga kataloger):

```
GET    /panel/sub-questions?module=&include_inactive=
POST   /panel/sub-questions
PATCH  /panel/sub-questions/{id}
GET    /panel/expert-profiles?module=&include_inactive=
POST   /panel/expert-profiles
PATCH  /panel/expert-profiles/{id}
```

- `key` och `module` är identitet: sätts vid create, ändras inte vid PATCH.
- Dubblett `(module, key)` → 409.
- `key` ska matcha `^[a-z0-9_]+$`. Expertprofil-key härleds från namn om den utelämnas.

GUI: **Verktyg** (bara admin) får två flikar:

1. **Kunder** — kryssrutor per kund × modul, PATCH vid ändring.
2. **Panelkatalog** — modulväljare (moduler med `panel_engine`), tabeller för sub-frågor och
   default-expertprofiler: skapa, redigera etikett/fält, sort_order, aktivera/inaktivera.

Ny sub-fråga syns i nästa panelkörning (samma som Fas 2 DB-insert, nu via UI).

---

## 4.5 Acceptanskriterium fas 4

- Frontend har `MODULE_REGISTRY`; rapportflikar och kampanj-modul-id kommer därifrån filtrerat
  på kundens `available_modules`.
- Admin kan slå på/av en modul för en kund i Verktyg → Kunder och se effekten på rapportflikar
  (efter omladdning).
- Admin kan lägga till en sub-fråga för `dd` i Verktyg → Panelkatalog utan kodändring.
- `POST /dd/campaigns` med `module: "politik"` (saknar `campaigns`) ger 400.
- Befintliga DD- och politik-flöden oförändrade för operatören som inte öppnar de nya flikarna.
