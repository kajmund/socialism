# 10 — PR 1 (B1): bryt Python-hostens domänimporter

**Blockerare:** B1 (`07-go-no-go.md` §4).
**Förutsättning:** [`09-contract-decision.md`](09-contract-decision.md) är
godkänt. Presentationen har ett eget steg — PR 1 rör **inte** researchbeteende.
**Bas:** `origin/main` `666eccb0` (denna utredning är PR 0).
**Storlek:** ~0,5–1 dag. Ren omdirigering + två nya små moduler + tester.

## 1. Mål

`backend/app/swe/` ska inte importera något från `app.config`, `app.jev` eller
`app.services`. Efter PR 1 gäller:

```console
$ grep -rnE "from app\.(config|jev|services)" backend/app/swe/ | wc -l
0
```

och samma grep ska vara ett **CI-gate** som failar vid återfall.

## 2. De fem ändringarna

| # | Nuvarande | Åtgärd | Ny plats | Bevis |
| --- | --- | --- | --- | --- |
| 1 | `definition.py:13` importerar `PROMPT_KEY_SET` från promptkatalogen; validerar ovillkorligt vid `:159` | `compile_definition(..., prompt_keys: Collection[str] \| None = None)` — **fail-closed**: en definition som innehåller provider-noder **kräver** en injicerad allowlist; saknas den blir det ett typat `SwdValidationError`. Definitioner utan provider-noder får utelämna parametern. | Signatur i `app/swe/definition.py`; anroparen (`runtime_preflight`, research) skickar katalogens nyckel-set | `provider_node_without_prompt_keys_is_rejected`, `provider_node_with_injected_prompt_keys_compiles`, `unknown_prompt_key_is_rejected_against_injected_set`, `definition_without_provider_nodes_needs_no_prompt_keys` |
| 2 | `runtime_dispatch.py:17` importerar `render_prompt`; används `:153` | Flytta den generiska 16-radsrenderaren till `app/swe/prompt_render.py`; `ProviderDispatch` tar en valfri `render: Renderer` så en host kan injicera egen policy | Ny modul `backend/app/swe/prompt_render.py` (flyttad, inte kopierad); `app/services/prompt_render.py` importerar/ re-exporterar `render_prompt` från SWE-modulen tills den tas bort i PR 5 | `test_swe_provider`: rendering via injicerad renderare respektive default; saknad prompt → `SwePreflightError` |
| 3 | `providers.py` (81 rader) importerar `app.config`, `app.jev.system`, `research.fast_controller` | **Flytta filen helt** till `backend/app/services/research/swe_providers.py`. Inga kodändringar i providern | `backend/app/services/research/swe_providers.py`; `backend/tests/test_swe_provider.py` importerar därifrån | Provider-testerna flyttas oförändrade; `app/swe` har inga JEV-namn kvar |
| 4 | `schema.py:16` `FEATURE_IDS` (Socialisms fem features) + `features.py` (host-kontext + OverGraph-katalogväg) | Flytta `FEATURE_IDS`, `CUSTOMER_ID_PATTERN`, `WorkflowHostContext`, `workflow_catalog_dir` till `backend/app/services/swe_host/context.py`. SWE tar en **opak `scope`** (`str`, valfri) där det behövs | Ny modul `backend/app/services/swe_host/`; `backend/app/swe/schema.py` behåller bara SWD-konstanter | `test_swe_features` flyttas till host-paketet; nytt SWE-test: opak scope accepteras utan feature-vokabulär |
| 5 | `__init__.py` exporterar `FEATURE_IDS`, `WorkflowHostContext`, `workflow_catalog_dir` | Exportera bara motor-API (`compile_*`, `canonical_json_bytes`, `sha256_hex`, `evaluate_expression`, `SWD_VERSION`, `NODE_TYPES`, `load_schema`, `SwdError`-familjen) | `backend/app/swe/__init__.py` | Import-gate + en test som pinnar `__all__` |

### 2.1 Vad som *inte* ändras

- `swe_bridge.py` importerar bara `app.swe.{definition,run_store,runtime,runtime_dispatch}`
  — inga ändringar krävs utom att promptkatalogens nycklar skickas in när
  bridge/wiring bygger kompilationen.
- Research-handlers, `execution.py`, `loop_control.py`, `claims.py`: orörda.
- SWD-schemat, `graph.py`, `joins.py`, `expression.py`, `runtime.py`: orörda
  utöver punkt 1–2.

## 3. Prompt-whitelisten är fail-closed (rättelse)

Första versionen föreslog att `prompt_keys=None` skulle tillåta varje
syntaktiskt giltig nyckel. Det vore en beteendeförändring: dagens
`compile_definition` kontrollerar **alltid** provider-noders nycklar mot
`PROMPT_KEY_SET` (`backend/app/swe/definition.py:152-163`), så en definition
med okänd prompt-nyckel avvisas idag. Kontraktet är därför:

| Fall | Beteende |
| --- | --- |
| Provider-nod + injicerad `prompt_keys` | Valideras mot setet; okänd nyckel avvisas |
| Provider-nod utan `prompt_keys` | **Typat kompileringsfel** (`unknown prompt_key ...`/saknad allowlist) — aldrig fail-open |
| Definition utan provider-noder | `prompt_keys` får utelämnas helt |
| Renderad prompttext saknas vid körning | Befintlig preflight-fel (`runtime_preflight.py`) oförändrat |

En ren strukturvalidering (bara formatkontroll, utan medlemskap) får om det
behövs senare vara ett **eget, explicit API** — aldrig standardbeteendet i
`compile_definition`. Detta uppfyller D5: B1 ändrar *var* katalogen kommer
ifrån, men försvagar inte kontrollen.

**Samma implementation, inte en kopia:** punkt 2 och 4 använder `git mv`-motsvarande
flytt (ny fil, gammal sökväg borttagen eller re-exporterande en enda gång).

## 4. Den nya gränsytan (blir kontraktet i PR 5)

```python
# app/swe/definition.py
def compile_definition(
    source: Mapping[str, Any], *,
    handlers: Collection[str] | None = None,
    providers: Collection[str] | None = None,
    prompt_keys: Collection[str] | None = None,   # NEW: host-supplied, like handlers/providers
) -> CompiledDefinition: ...

# app/swe/runtime_dispatch.py
Renderer = Callable[[Mapping[str, str], str, Mapping[str, Any]], str]

@dataclass(frozen=True)
class ProviderDispatch:
    providers: Mapping[str, Provider]
    prompts: Mapping[str, str] | None = None
    cache: DecisionCache | None = None
    render: Renderer | None = None   # NEW: default = app.swe.prompt_render.render_prompt
```

`scope` i SWE är bara en opak etikett (för loggning/adapterval) — inga
feature-id:n, ingen katalogväg.

## 5. CI-gate

Nytt litet test (eller steg i `swe-runtime`-jobbet):

```python
_DOMAIN = re.compile(r"^\s*(from|import)\s+app\.(config|jev|services)\b", re.MULTILINE)

def test_swe_package_has_no_domain_imports() -> None:
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(Path("app/swe").glob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if _DOMAIN.match(line)
    ]
    assert offenders == []
```

Gaten körs i `swe-runtime`-jobbet och kan inte kringgås med lokal pin.

## 6. Tester

| Test | Ändring |
| --- | --- |
| `test_swe_definition.py` (18) | Uppdatera prompt_key-testerna till injicerat set + de fyra fail-closed-testerna i §3 |
| `test_swe_features.py` (5) | Flyttas till host-paketet (`tests/test_swe_host_context.py`) |
| `test_swe_provider.py` (13) | Importrad ändras till `app.services.research.swe_providers`; testet för JEV-adaptern stannar här |
| `test_swe_runtime_*.py`, `test_swe_joins.py`, `test_swe_expression.py`, `test_swe_canonicalize.py`, `test_swe_persistence.py` | Oförändrade |
| `test_swe_import_boundary.py` (ny) | §4-gaten + `__all__`-pinning |
| `tests/test_research_swe/test_wiring.py` (4) | Oförändrat; ska vara grönt |

## 7. Acceptanskriterier

1. `grep -rnE "from app\.(config|jev|services)" backend/app/swe/` → **0**.
2. `app/swe/__init__.py` exporterar inga host-/produktnamn.
3. Research- och wiring-testerna gröna, oförändrade eller med bara
   importvägsändringar; inga Research-beteenden ändrade.
4. `make test-swe` (cargo test + pytest) grönt.
5. `crates/swe-reference` opåverkat och grönt.
6. Ingen ny semantiktyp i Python (den väntar på PR 2).
7. **Ingen försvagad kontroll:** en provider-nod utan injicerad allowlist avvisas
   typat; det finns inget läge där en okänd prompt-nyckel kompilerar.

## 8. Risker

| Risk | Mildring |
| --- | --- |
| Prompt-key-katalogen glöms i någon anropare → provider-decision avvisas sent | Gaten/testet kompilerar en provider-workflow via bryggan; preflight-felet är typat och tydligt |
| Re-exporten av `render_prompt` skapar två sökvägar | Re-export tills PR 5, sedan bort; aldrig två implementationer (den gamla filen importerar SWE-modulen) |
| Host-kontextflytten bryter benchmark-skript | `benchmark_research_swe*.py` importerar den nya sökvägen; greps i PR:en |

## 9. Vad som INTE görs här

- Inga generiska behovs-, evidens- eller operationstyper (PR 2).
- Ingen journaländring (PR 3).
- Ingen flytt av `swe-gym`, ingen licensfråga, ingen ny repo-struktur.
