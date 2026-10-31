# SWE som självständigt projekt — utredning Fas A–F

**Status:** Utredning och förberedelse. **Ingen fysisk repo-flytt är gjord eller
beslutad.** Ingen produktions-Research och inget pågående blindtest v3 ändras av
detta arbete.
**Bas:** `origin/main` `666eccb0cc61f4a5e15e95bc1e1edfbdf75b32e1`.
**Frågan:** kan Socialism Work Engine (SWE) bli ett självständigt, versionerat
projekt som Socialism konsumerar — och var går i så fall gränsen mot Socialisms
domän?

## Beslut i korthet

**NO-GO för omedelbar fysisk flytt. GO för extraktionsprogrammet** efter att
blockerarna B1–B3 är åtgärdade (`07-go-no-go.md`). Kärnan är generisk och
referensexperimentet fungerar offline; det som återstår är att vända fem
domänimporter i Python-hostlagret, befrämja de generiska
behovs-/evidens-/operations-/budgetförmågorna till SWE, och ge
paus/återupptagning ett Rust-kontrakt. Det är små, mekaniska åtgärder — inte en
ny arkitektur.

**Projektägaren har godkänt riktningen (2026-10-31)** med en ändrad ordning:
kontraktsbeslutet ligger före B1, B1–B3 genomförs som tre separata PR:er, och
den fysiska flytten sker först därefter. Se `07` §0 och
[`09-contract-decision.md`](09-contract-decision.md).

**SWE Core är inte hela SWE.** Målbilden är SWE = Workflowmotor · Behov ·
Evidens · Operationer · Budget · Providers · Exekveringsjournal; Socialism =
Research · JEV · OverGraph · GLiNER2 · Juridiska operationer · Dokument och
rättskällor; separat experimentinfrastruktur = `swe-budget` / `swe-bench`.

## Leveranser

| # | Leverans | Svarar på | Läs den om du vill veta |
| --- | --- | --- | --- |
| — | [`01-inventory-rust.md`](01-inventory-rust.md) | Fas A | Varje Rust-moduls placering, ansvar, beroenden, domänkoppling, ägare och åtgärd; externberoenden; test-/fixture-/benchmarkinventering; riktiga testresultat |
| — | [`02-inventory-python.md`](02-inventory-python.md) | Fas A | Alla 23 filer i `backend/app/swe`; research-bryggan; OverGraph-/JEV-adaptrarna; test- och CI-inventering; faktisk importriktning med grep-bevis |
| — | [`03-ownership-matrix.md`](03-ownership-matrix.md) | Fas B | Vad som tillhör SWE respektive Socialism, med regel, gränsfall och beslutspunkter |
| — | [`04-public-contracts.md`](04-public-contracts.md) | Fas C | Vilka API:er som måste vara stabila: workflow, needs, evidence, operations, budget, providers, policy, historik, benchmark |
| — | [`05-gym-split.md`](05-gym-split.md) | Fas E | Modul-för-modul-uppdelning av `swe-gym`: generisk kärna vs juridiskt domänexperiment, och vad som inte får följa med |
| — | [`06-extraction-plan.md`](06-extraction-plan.md) | Fas F | Målstruktur för nya repot, filer som flyttas, historik, workspace, versionering, konsumtion, CI, risker och PR-ordning |
| — | [`07-go-no-go.md`](07-go-no-go.md) | Beslutspunkt | Bevisat redo / inte redo, blockerare B1–B4, GO-grind och rekommendation |
| 08 | [`08-verification-log.md`](08-verification-log.md) | Verifiering | Kommandon och resultat: 30/30 kärntester, 106/106 gymtester, 11/11 demotest, demo-run, importgates, CI-validering och korsgranskningens åtgärder |
| 09 | [`09-contract-decision.md`](09-contract-decision.md) | Beslut (B1–B3) | Rust som enda sanningskälla, versionssatta serialiseringskontrakt, journalens försök/bekräftelse/debitering, ramverksgränsen, och att B1 inte får göra Python-adaptern självständig för tidigt |
| 10 | [`10-pr1-b1-python-boundary.md`](10-pr1-b1-python-boundary.md) | PR 1 (B1) | De fem domänimporterna, exakt vart de flyttar, ny gränsyta, CI-gate och acceptanskriterier |
| 11 | [`11-pr2-b2-core-contracts.md`](11-pr2-b2-core-contracts.md) | PR 2 (B2) | Generiska needs/evidence/operations i `swe-core` som normativ Rust, `swe-budget`, Python-projektion och differentialtestet |
| 12 | [`12-pr3-b3-journal-resume.md`](12-pr3-b3-journal-resume.md) | PR 3 (B3) | Journal-/resume-kontraktet: run-snapshot, försök, bekräftade resultat, debitering, återhämtningsstrategier och de garantier som får/ inte får påstås |
| — | [`../../crates/swe-reference/`](../../crates/swe-reference/README.md) | Fas D | Körbart, testat, helt offline domänneutralt referensexperiment (leverantörsval) |

Leveranserna är isolerade i en PR: nya dokument (`README` + `01`–`12`), en ny
crate och en CI-rad. **Ingen befintlig produktionskod ändras.** Dokument `09`–`12`
är besluts- och PR-underlag för B1–B3; de implementerar ingenting.

## Referensexperimentet (Fas D)

`crates/swe-reference` besvarar frågan *"Vilken leverantör erbjuder lägst pris
och uppfyller samtliga tre krav?"* med **Beta** — utan att workflowet får
svaret. Det visar tio saker med riktig motorexekvering:

1. behov härleds från operationskontrakt,
2. information hämtas via en deterministisk mock-provider,
3. saknade uppgifter upptäcks och hanteras,
4. evidens verifieras som VERIFIED / AMBIGUOUS / REJECTED med källreferens,
5. operationens `required_inputs` kontrolleras med ALL_REQUIRED,
6. en deterministisk jämförelse väljer billigaste kompatibla leverantör,
7. undersökningen avstår med `INSUFFICIENT_EVIDENCE` när evidens saknas,
8. faktisk Sweycoin-förbrukning redovisas per åtgärd och totalt,
9. en pågående undersökning kan pausas och återupptas utan dubbeldebitering,
10. en operation upptäcker ett nytt behov och returnerar `NeedMore`.

Kör själv (offline):

```sh
export PATH="$HOME/.cargo/bin:$PATH"
cd crates/swe-reference
cargo test --offline
cargo run --offline
```

Craten importerar varken Socialisms Python-backend, juridiska datatyper,
OverGraph, GLiNER2, dokumentmodellen eller produktkonfigurationen. Den använder
endast `swe-native` (motorn) och `swe-gym::ledger` (den befintliga Sweycoin-
ledgern — återanvändning, inte en kopia).

## Så verifieras utredningen

```sh
# Rust-kärnan (domänfri)
cargo test --offline --manifest-path crates/swe-native/Cargo.toml

# Gym-experimentet (baslinje, ändras inte av utredningen)
cargo test --offline --manifest-path crates/swe-gym/Cargo.toml

# Referensexperimentet
cargo test --offline --manifest-path crates/swe-reference/Cargo.toml
cargo run --offline --manifest-path crates/swe-reference/Cargo.toml

# Importriktning: inga domänimporter i app/swe (endast kända läckage före PR 1)
grep -rnE "from app\.(config|jev|services)" backend/app/swe/

# Offline-bevis för demon: inga nätverksberoenden i crates/swe-reference utöver
# de två path-beroendena; mock-providern är deterministisk.
grep -rn "swe_gym" crates/swe-reference/src crates/swe-reference/tests
```

Faktiska testresultat, kommandon och utdata dokumenteras dels i
inventeringarnas Evidence-avsnitt, dels i referensexperimentets README.

## Avgränsning och osäkerheter

- Inventeringarna är statiska läsningar + offline-testkörningar; ingen
  produktionsmiljö, databas eller modell har anropats.
- `swe_native`-extensionen är inte byggd i denna worktree, så backendens
  pytest-svit har inte körts. Rust-kärnan och referensexperimentet är däremot
  byggda och testade offline.
- Paus/återupptagning är bevisat på host-nivå i demon; Socialisms
  `RunStore`-kontrakt är testat men inte produktionskopplat
  (`swe_bridge.py` skickar `run_store=None`). Det står uttryckligen i
  `04`/`07`.
- OverGraph Owner-regelns tillämpning på SWE-kataloger är markerad osäker
  eftersom ingen SWE-katalog är produktionskopplad i dag.
- Grova tidsuppskattningar i `07` är planeringsunderlag, inte åtaganden.
