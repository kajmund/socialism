# Audit D — obsolet/död kod i `frontend/src/**` och `word-addin/src/**`

> **Uppdatering 2026-10-18:** Flera av fynden nedan är genomförda enligt borttagningspolicyn
> (kod som bara nåddes av icke-experimentella tester). Se [syntesens §6](obsolete-2026-10-18.md#6-borttagningar-genomförda-enligt-borttagningspolicyn-2026-10-18).
> Rapporten i övrigt beskriver läget före borttagningarna.

**Repo:** `/Users/erikfremred/socialism` · **Branch:** `fix/sme-group-chat-voice` (arbetskopia, ~613 modifierade / ~397 untracked filer)
**Omfattning:** frontend-appkod (444 filer under `frontend/src`) + word-addin (44 filer under `word-addin/src`). Testfiler ägs av annan medlem; de nämns bara som stödbevis (test-only moduler, döda i18n-nycklar).
**Read-only:** inga källändringar, inga installationer, ingen build, inga nätverksanrop. Endast denna fil skrevs.

---

## 1. Metod (så att fynden kan reproduceras)

| Steg | Verktyg | Vad som gjordes |
|---|---|---|
| Reachability | Python-skript (`/tmp/obsolete-audit/fe/`) | Importgraf från `frontend/src/main.tsx`: statiska `import`/`export from`, dynamiska `import("…")`, `React.lazy(() => import(...))`, `new URL("…", import.meta.url)` (worklets/workers). Alias `@/*` → `src/*`, index-upplösning. 444 filer, 5 oanvändbara. |
| Export-användning | Python + Node | Extraherade alla `export function/const/class/type/interface` + `export {…}`; räknade **råa identifierarförekomster** i alla `.ts/.tsx` utanför den egna filen (fångar även `import`, re-export, `typeof`, testfiler). Slutkandidat kräver **0 förekomster utanför egen fil** → eliminerar falska positiver som `module.X` efter dynamisk import. |
| Transitiv död | Python | Prod-reachabla filer vs. icke-reachabla: exporter som bara konsumeras av oanvända filer → "transitivt döda". |
| i18n | Node (importerar `sv.ts`/`en.ts` via native TS) | Plattade 3158 nycklar; räknade literal förekomster av varje nyckel i alla filer utanför `i18n/messages`; detekterade dynamiska byggen `` t(`prefix.${x}`) `` (11 prefix) → C-risk; paritet sv/en. |
| npm-beroenden | Node | Import-scan av `package.json` dependencies mot all `src` + `index.html` + `vite.config.ts`. |
| CSS | Python | Parsade alla 836 regelblock i `styles/admin-runs.css` + `index.css`; klassnamn som inte förekommer i någon `.ts/.tsx/.html` (exkl. dynamiska `` `chat-md-${tag}` ``). |
| word-addin | Samma skript | Reachability 44 filer, export-räkning, i18n-nycklar, samt cross-check av 9 endpoint-paths mot backend-routers. |
| Git-status | `git status --porcelain`, `git ls-files --error-unmatch` | Varje fynd markerat **tracked/clean** (etablerad kod) eller **M/??** (WIP i feature-branchen). |

**Bekräftade falska positiver som INTE flaggas:** `components/chat/pcmCapture.worklet.ts` och `products/sme/sileroModel.worker.ts` (laddas via `new URL(..., import.meta.url)`), `products/sme/sileroModel.ts`/`sileroGate.ts` (dynamisk `import()` + destrukturering i `speechVad.ts`), `components/underlag/{Pdf,Docx}KnowledgeViewer.tsx` (`React.lazy`), `chat-md-h1..h4` (dynamisk klass `` `chat-md-${heading.tag}` ``), `MODULE_REGISTRY`-nycklar/`frontendEntry` (backend-drivna), `frontend/mockup/extracted/**` (visuell källa enligt AGENTS.md).

---

## 2. Sammanfattning per kategori

| Kategori | Antal | Allvarlighet | Verdict |
|---|---|---|---|
| Helt oanvändbara källfiler (frontend) | **5 filer / 360 rader** | Hög — etablerad, tracked, orörd i branchen | **A** |
| Transitivt döda API-kluster (endast använda av döda filer) | **5 symboler + 30 i18n-nycklar** | Hög | **A/B** |
| Helt döda exporter i levande filer (frontend) | **27 symboler** (varav 14 API-wrappers) | Medel | **A** |
| Överexporterade men internt använda symboler | **39** | Låg | **B** |
| Döda i18n-nycklar (bevisat literal-fria) | **163** (+30 transitivt döda) | Medel | **A/B** |
| i18n-nycklar med dynamisk falsk-positiv-risk | **144** (11 prefix) | — | **C** |
| Döda CSS-regler (`admin-runs.css`) | **36 unika regler + 1 `.mono`-dubblett** | Låg/medel | **A/B** |
| Döda assets | **2 PNG/SVG** (`hero.png`, `vite.svg`) | Låg | **A** |
| Oanvända npm-beroenden | **0** (alla 22 används) | — | — |
| word-addin: döda filer / oanvända deps / saknade endpoints | **0 / 0 / 0** (9/9 endpoints finns) | — | — |
| word-addin: överexporterade symboler + döda i18n-nycklar | **25 + 7** | Låg | **B** |
| Döda/oreachable routes eller nav-länkar | **0** (69 route-paths, 43/43 sidor routade, alla nav-paths matchar) | — | — |

**i18n-paritet:** `sv` = `en` = 3158 nycklar, **0** saknade i någon katalog (TypeScript-typningen håller). Problemet är enbart oanvända nycklar, inte asymmetri.

---

## 3. Helt oanvändbara filer (Verdict A, tracked/clean)

Reachability från `main.tsx` (inkl. lazy/dynamic/worker): 0 inkommande kanter. Dessutom: identifieraren förekommer **0 gånger** utanför filen i hela `frontend/`.

| Fil | Rader | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `components/reports/ReportVerdictCalibrationPanel.tsx` | 175 | 0 imports; `ReportVerdictCalibrationPanel` 0 träffar utanför filen; dess enda konsumenter (`getVerdictCalibration`/`saveVerdictCalibration`) är i sin tur oanvända | A | Ta bort panel + wrappers + 30 i18n-nycklar, **eller** koppla in i `pages/ReportPage.tsx` (backend-endpoints `GET/POST /reports/{id}/verdict-calibration` finns kvar i `backend/app/api/reports.py:434,453`) |
| `components/dd/DdSourcingCriteriaFields.tsx` | 98 | 0 imports; `DdSourcingCriteriaForm`/`DdSourcingCriteriaReadout` 0 träffar; importerar `defaultDdCriteria` (också död) | A | Ta bort; backend har kvar `/dd/sourcing/search` + `/dd/campaigns/{id}/sourcing/run` (`backend/app/api/dd.py:203,232`) → frontend-delen av DD-sourcing är övergiven |
| `components/dd/DdResearchAppointmentsTable.tsx` | 54 | 0 imports; `DdResearchAppointmentsTable` 0 träffar; enda användare av `dd.panel.researchAppointment*`-nycklarna | A | Ta bort + 5 i18n-nycklar |
| `pages/PlaceholderPage.tsx` | 24 | 0 imports; ingen route i `App.tsx` pekar på den; hårdkodad svenska (`"Skapa ny körning"`), bryter i18n-kravet | A | Ta bort |
| `lib/ddExpertRoles.ts` | 9 | 0 imports; **exakt duplikat** av `expertRoleKey` i `lib/expertKey.ts:2` (samma JSDoc, samma implementation) | A | Ta bort filen; behåll en implementation (se §6) |

---

## 4. Transitivt döda kluster (Verdict A/B)

Symboler som bara konsumeras av filerna i §3 — dvs. döda trots att de "används".

| Symbol | Fil:rad | Konsument | Verdict | Förslag |
|---|---|---|---|---|
| `getVerdictCalibration` | `api/reports.ts` | endast `ReportVerdictCalibrationPanel.tsx` | A | Ta bort med panelen |
| `saveVerdictCalibration` | `api/reports.ts` | endast panelen | A | Ta bort |
| `VerdictCalibration` (typ) | `api/reports.ts` | endast panelen | A | Ta bort |
| `DdSourcingCriteria` (typ) | `api/dd.ts` | endast `DdSourcingCriteriaFields.tsx` | A | Ta bort |
| `DdResultatFilter` (typ) | `api/dd.ts` | endast samma fil | A | Ta bort |
| 30 i18n-nycklar | se nedan | endast de 3 döda komponenterna | A | Ta bort |

**i18n-nycklar som bara refereras från döda filer** (30 st):
`dd.sourcing.briefLabel`, `dd.sourcing.alderMin`, `dd.sourcing.alderMax`, `dd.sourcing.omrade`, `dd.sourcing.omradePlaceholder`, `dd.sourcing.fritext`, `dd.sourcing.fritextPlaceholder`, `dd.panel.researchAppointmentsEmpty`, `dd.panel.researchAppointmentPerson`, `dd.panel.researchAppointmentCompany`, `dd.panel.researchAppointmentOrgnr`, `dd.panel.researchAppointmentInGroup`, `dd.panel.researchAppointmentInGroupYes`, `reports.verdictCalibration.title`, `.intro`, `.action`, `.score`, `.arm`, `.verdictKey`, `.question`, `.matchesYes`, `.matchesNo`, `.note`, `.notePlaceholder`, `.save`, `.saving`, `.saved`, `.loadError`, `.saveError`, `.choiceRequired`.

---

## 5. Helt döda exporter i levande filer (27, Verdict A)

Bevis: identifieraren förekommer **exakt en gång** i hela `frontend/src` (definitionen) — 0 träffar i prod-kod *och* i testfiler. Alla filer nedan är tracked/clean utom de markerade **M**.

### 5a. API-wrappers utan anropare (14)

| Fil:rad | Funktion | Backend-endpoint finns? | Verdict | Förslag |
|---|---|---|---|---|
| `api/catalog.ts:51` | `updateCatalogList` | ja | A | Ta bort wrapper |
| `api/dd.ts:277` | `defaultDdCriteria` | (lokal helper) | A | Ta bort med §3-filen |
| `api/dd.ts:198` | `runDdCampaignSourcing` | ja (`/dd/campaigns/{id}/sourcing/run`) | A | Ta bort frontend-del; endpoint kvar |
| `api/dd.ts:214` | `searchDdSourcing` | ja (`/dd/sourcing/search`) | A | Ta bort frontend-del |
| `api/kunder.ts:24` | `getKund` | ja | A | Ta bort (listning används via annan wrapper) |
| `api/labelVocabularies.ts:36` | `listLabelVocabularies` | ja | A | Ta bort |
| `api/llmSettings.ts:124` | `putLlmSettings` | ja | A | Ta bort (annan write-väg används) |
| `api/panel.ts:51` | `createPanelSession` | ja | A | Ta bort |
| `api/populations.ts:120` | `generatePopulation` | ja | A | Ta bort (job-vägen används) |
| `api/rattsunderlag.ts:126` | `rattsunderlagHref` | — | A | Ta bort |
| `api/reports.ts:155` | `reportHtmlUrl` | ja | A | Ta bort; `getReportHtml()` används i stället |
| `api/runs.ts:229` | `runPersonaInterview` | ja | A | Ta bort wrapper (panelen `RunPersonaInterviewPanel` används av `OasisResultsPanel.tsx:78` och ska behållas) |
| `api/sme.ts:73` | `getSmeExpertTurn` | ja | A | Ta bort (**OBS filen är M** — WIP-risk, se §12) |
| `api/users.ts:29` | `updateUser` | ja | A | Ta bort |

### 5b. Övriga helt döda symboler (13)

| Fil:rad | Symbol | Bevis/not | Verdict | Förslag |
|---|---|---|---|---|
| `components/runs/feedCopy.tsx:267` | `CopyAttemptButton` | 0 anrop; `CopyFeedTextButton` i samma fil används av `OasisResultsPanel.tsx` | A | Ta bort knappen + `formatAttemptForClipboard` (`:204`, enda anroparen är knappen) |
| `components/runs/liveFeedFromVariant.ts:318` | `attemptHasLiveFeed` | 0 anrop | A | Ta bort |
| `components/chat/geminiLiveProtocol.ts:183` | `GEMINI_OUTPUT_SAMPLE_RATE` | dubbel-exponering av intern `OUTPUT_SAMPLE_RATE` (`:9`) | A | Ta bort exporten |
| `components/chat/geminiLiveProtocol.ts:184` | `GEMINI_INPUT_SAMPLE_RATE` | dubbel-exponering av `INPUT_SAMPLE_RATE` (`:8`) | A | Ta bort exporten |
| `data/library.ts:37` | `FP_DETAIL_LABELS` | 0 anrop; hårdkodade svenska fältetiketter (i18n-migrationen klar) | A | Ta bort |
| `data/runs.ts:13` | `RUN_STATUS_LABEL` | 0 anrop; ersatt av `t("runs.status.*")` (se `pages/DashboardPage.tsx:40-46`); JSDoc säger "Fallback … not yet on useLocale" | A | Ta bort |
| `data/runs.ts:152` | `extractDomain` | 0 anrop | A | Ta bort |
| `data/runs.ts:161` | `looksLikeVideo` | 0 anrop | A | Ta bort |
| `lib/helpSession.ts:22` | `resetHelpSessionId` | 0 anrop (modulen används för övriga funktioner) | A | Ta bort funktionen |
| `lib/helpView.ts:162` | `helpViewKey` | 0 anrop | A | Ta bort funktionen |
| `modules/moduleRegistry.ts:18` | `MODULE_IDS` | 0 anrop; registry exponerar redan `MODULE_REGISTRY`/`manifestsForIds` | A | Ta bort exporten |
| `modules/moduleRegistry.ts:20` | `getModule` | 0 anrop | A | Ta bort exporten |
| `products/sme/workspaceChatLogic.ts:114` | `isWorkspaceServerTool` | 0 anrop (**filen är M** — WIP-risk) | A/B | Verifiera mot pågående voice-arbete innan borttagning |

**Not:** `api/runs.ts::runPersonaInterview` (död wrapper) ska inte förväxlas med `components/runs/RunPersonaInterviewPanel.tsx`, som importeras av `OasisResultsPanel.tsx:78` och alltså är levande.

---

## 6. Test-only produktionsmoduler (Verdict B/C — stödbevis till test-auditen)

Moduler som **inte nås från `main.tsx`** men nås från egna testfiler. Det är produktionskod i `src/` som bara existerar för sina tester.

| Fil | Rader | Enda konsument | Filstatus | Verdict | Förslag |
|---|---|---|---|---|---|
| `lib/expertKey.ts` | 19 | `lib/expertKey.test.ts` | tracked/clean | **A** (död) | Prod använder varken denna eller `lib/ddExpertRoles.ts` (§3). Ta bort **båda** filerna + testet, eller behåll `expertKey.ts` som enda implementation och använd den i `pages/DdCampaignEditorPage`-flödet |
| `products/sme/smeTurnRecovery.ts` | 44 | `products/sme/smeTurnRecovery.test.ts` | tracked/clean | **A/B** | `smeTurnRecoveryAction`/`shouldKeepSmeTurnPending` anropas inte i prod (status-flödet ligger i `api/sme.ts`/`useSmeChatSocket.ts`). Ta bort kod + test eller koppla in i återhämtningsflödet |
| `components/execution/executionFixtures.ts` | 195 | 3 testfiler (`ExecutionInspector.test.tsx`, `fetchPolicy.test.ts`, `evidenceRefs.test.ts`) | tracked/clean | **C** | Legitima testfixtures i prod-träd — flytta till `*.test.fixtures.ts`/test-mapp eller behåll medvetet |

Ytterligare **30 exporter i prod-reachabla filer** konsumeras bara av testfiler (inte av prod; verifierat med råa identifierarträffar i prod-filer). De är typiska "exporterade för testbarhet" och inte obsoleta i sig, men kandidater att göra icke-exporterade om testet kan testa via publik API: `sileroGate.ts::resample`, `turnVad.ts::TurnVad`, `speechVad.ts::sileroThresholdsFromConfig`, `workspaceChatLogic.ts::{clientToolFailure,expertProxyToolNames,isCurrentConversation,workspaceSessionTool}`, `geminiLiveProtocol.ts::decodeGeminiLiveFrame`, `liveToolWake.ts::{deferredToolResult,shouldDeferLiveTool}`, `components/dd/researchPeople.ts::{formatAppointments,formatSeats}`, `evidenceRefs.ts::{foundItemsInOrdinalOrder,parseEvidenceRef}`, `legalSourceDisplay.ts::{citationFromLagenNuUrl,isLegalFrontMatter}`, m.fl. (full lista i `/tmp/obsolete-audit/fe/prod_exports2.json`).

---

## 7. Överexporterade symboler — bara `export`-nyckeln är död (39, Verdict B)

Används internt i sin egen fil men importeras aldrig någon annanstans. Åtgärd: **ta bort `export`**, behåll koden.

| Kategori | Symboler |
|---|---|
| API | `api/personas.ts::listPersonas` (används av 3 interna wrappers) |
| shadcn/ui (intern användning) | `components/ui/button.tsx::buttonVariants`, `badge.tsx::badgeVariants`, `dialog.tsx::{DialogPortal,DialogOverlay,DialogTrigger}`, `card.tsx::{CardAction,CardDescription,CardFooter}` |
| chat/voice | `chatWindow.ts::CHAT_MESSAGE_LIMIT`, `liveToolWake.ts::VOICE_TOOL_WAKE_PREFIX` |
| runs | `activityFeed.ts::{CARD_COVERED_ACTIONS,NOISE_ACTIONS,DEFAULT_SIMULATED_TIME_WINDOW,isTimelineAction,tickIndexForTime}`, `TickDayModal.tsx::TickEditorBody`, `feedCopy.tsx::formatAttemptForClipboard` |
| dd/panel/execution | `researchGroup.ts::hasFigures`, `researchPeople.ts::{isAuditorRole,matchesPersonSearch}`, `evidenceRefs.ts::itemIdFromEvidenceRefs`, `PanelLiveFeedList.tsx::revealedPanelRounds` |
| data | `expert-tools.ts::{catalogExpertToolIds,isExpertToolId}`, `runs.ts::normalizeTick` |
| i18n/modules | `i18n/locales.ts::{LOCALE_STORAGE_KEY,isLocale}`, **`i18n/index.ts`-barrel: `DEFAULT_LOCALE`, `LOCALES`, `LOCALE_LABELS`, `intlLocale`, `translate`** (importeras bara via `./locales`/`./t` — 5 döda re-exports), `modules/manifest.ts::MODULE_COMPONENT_IDS`, `moduleRegistry.ts::modulesWith`, `moduleHomePaths.ts::MODULE_HOME_PATHS`, `report-modules.ts::REPORT_MODULES` |
| lib | `auth.ts::MagicLinkError` (kastas internt), `expertgranskningReport.ts::sessionReports`, `scoping.ts::customerIdForScope` |
| products/sme | `smeResearchJobs.ts::isResearchJob`, `workspaceChatLogic.ts::{workspaceClientToolNames,workspaceServerToolNames}`, `workspaceLocalSelection.ts::selectionsSameGeometry` |

---

## 8. i18n: döda nycklar (Verdict A/B) och dynamisk C-risk

`sv.ts`/`en.ts` = 3158 nycklar vardera, 0 paritetsfel. **163 nycklar** har noll literal-referenser utanför `i18n/messages/**` + 30 transitivt döda (§4) = **193 bevisat döda**. Därtill **144 nycklar (C)** under 11 prefix som byggs dynamiskt och därför **inte** får raderas utan verifiering.

### 8a. Per sektion (döda / totalt / andel)

| Sektion | Totalt | Döda | Död% | Kommentar |
|---|---:|---:|---:|---|
| `voiceWorkspaceChat` | 199 | 76 | 38 % | **alla 76 är C-risk** (dynamiska `voiceWorkspaceChat.${status}`) |
| `dd` | 353 | 65 | 18 % | 47 bekräftade + 18 C; hela DD-sourcing/research-blocken är döda |
| `execution` | 155 | 26 | 17 % | 2 bekräftade + 24 C (`eventTypes.*`/`stages.*` byggs dynamiskt) |
| `configurations` | 143 | 23 | 16 % | hela `configurations.editor.reportThresholds.*` + intro/language-blocken döda |
| `runs` | 489 | 20 | 4 % | `runs.live.*`, `runs.results.*`, `runs.interview.role*` döda |
| `sme` | 102 | 15 | 15 % | röst-/samtalsknappar borta |
| `profile` | 34 | 12 | 35 % | **alla C-risk** (`profile.${field}`) |
| `rattsunderlag` | 69 | 11 | 16 % | gamla platta nycklar; sidan använder `rattsunderlag.list.*` |
| `documentBatch` | 22 | 9 | 41 % | **alla C-risk** (`documentBatch.stage.${stage}`) |
| `reports` | 83 | 6 | 7 % | 6 bekräftade (`backToJobs`, `duration.*`); därtill 17 `reports.verdictCalibration.*` som är transitivt döda (§4) |
| `feedback`, `experts`, `expertPanels`, `bolag`, `config`, `populations`, `spinndoctor`, `chat`, `common`, `personas`, `underlag`, `dashboard`, `help`, `messages`, `tools`, `playground`, `anchorSets`, `expertgranskning` | — | 1–5 var | — | se bilaga |

### 8b. C-risk-prefix (dynamiska nyckelbyggen — rör ej utan verifiering)

`dd.campaigns.status` (6), `dd.panel.panelStatus` (5), `dd.panel.researchStatus` (4), `dd.sourcing.resultatOptions` (3), `documentBatch.stage` (9), `execution.researchMonitor.eventTypes` (20), `execution.researchMonitor.stages` (4), `profile` (12), `voiceWorkspaceChat` (76), `workspaceChat` (5) — 144 nycklar totalt. Exempel på byggen: `` t(`execution.researchMonitor.eventTypes.${event.event_type}`) `` (`ResearchEventLog.tsx`), `` t(`profile.${key}`) `` (`ProfileForm.tsx`), `` t(`voiceWorkspaceChat.${status}`) ``.

### 8c. Fullständig lista bekräftat döda nycklar (163) — bilaga

- **dd** (47): `dd.campaigns.list.moduleHeading`, `dd.campaigns.detail.title`, `dd.sourcing.run`, `dd.sourcing.running`, `dd.sourcing.runDone`, `dd.sourcing.runError`, `dd.sourcing.stepCriteria`, `dd.sourcing.stepResults`, `dd.sourcing.search`, `dd.sourcing.searching`, `dd.sourcing.lockedIntro`, `dd.sourcing.resultsEmpty`, `dd.sourcing.backToCriteria`, `dd.panel.expertPanelTitle`, `dd.panel.expertPanelIntro`, `dd.panel.expertPanelSelected`, `dd.panel.panelsLoading`, `dd.panel.manageExpertPanels`, `dd.panel.runConfigIntro`, `dd.panel.runResearchPageIntro`, `dd.panel.runResultsPageIntro`, `dd.panel.researchAppointmentRole`, `dd.panel.researchTitle`, `dd.panel.researchIntro`, `dd.panel.researchRunAgain`, `dd.panel.researchPeopleNeedClear`, `dd.panel.researchNoSubsidiaries`, `dd.panel.researchExpandPerson`, `dd.panel.researchCollapsePerson`, `dd.panel.researchDossierTitle`, `dd.panel.researchCompanies`, `dd.panel.researchOtherCompanies`, `dd.panel.applyPanelToAll`, `dd.panel.applyPanelToAllPlaceholder`, `dd.panel.candidatePanelLabel`, `dd.panel.expertRolesTitle`, `dd.panel.expertRolesIntro`, `dd.panel.rolesLoading`, `dd.panel.rolesEmpty`, `dd.panel.selectAllCandidates`, `dd.panel.clearCandidates`, `dd.panel.selectCandidate`, `dd.panel.savingSelection`, `dd.panel.noExpertsSelected`, `dd.panel.reportFailed`, `dd.panel.openReport`, `dd.panel.backToCampaigns`
- **configurations** (23): `configurations.editor.{newIntro,editIntro,languageLabel,languageHint,anchorHint}` + `configurations.editor.reportThresholds.{title,intro,resetDefaults,posStrongHint,posMixedHint,critWeakHint,diffClearHint,diffWeakHint,topicDriftHint,actionReadyHint,actionMinorAdjustHint,actionReviseHint,advancedToggle,triggerStrongPosHint,takeawayPosStrongHint,takeawayPosWeakHint,takeawayCritHighHint,takeawayContrastGapHint}`
- **runs** (20): `runs.tick.roundsTitle`, `runs.results.{attemptCount,attemptOrdinal,compareHint,moreActions,failed,variantCount,variantSummary,networkForVariant,liveFeedAria,liveFeedTitle}`, `runs.live.{round,roundOf,commentId,dayBadge,postCollapsed,commentCollapsed}`, `runs.feed.simTime`, `runs.interview.{roleUser,rolePersona}`
- **sme** (15): `sme.{activeNow,voice,voiceEnable,voiceDisable,listeningStart,listeningStop,sourceChecked,floor,send,sending,reconnecting,call,videoCall,information,expertEditorTitle}`
- **rattsunderlag** (11): `rattsunderlag.{title,intro,start,starting,startError,loadError,historyTitle,historyEmpty,resultEmpty,openReport,status.pending}`
- **reports** (6): `reports.backToJobs`, `reports.duration.{seconds,minutes,minutesSeconds,hours,hoursMinutes}`
- **feedback** (5): `feedback.col{Kind,Title,Status,Created,Actions}`
- **experts** (4): `experts.list.column{Name,Background,Updated}`, `experts.avatar.hint`
- **bolag** (3): `bolag.nav.{expertgranskning,feedback,jobs}` · **config** (3): `config.page.{title,intro,sectionDdExpertpanel}` · **expertPanels** (3): `expertPanels.list.column{Name,Size,Updated}` · **populations** (3): `populations.detail.personasCount`, `populations.builder.{loadPopulationError,editBanner}` · **spinndoctor** (3): `spinndoctor.{toggleCanvas,hideCanvas,canvasAria}`
- **chat** (2): `chat.imageTooLarge`, `chat.imageTypeNotAllowed` · **common** (2): `common.editRecipe`, `common.loadError` · **execution** (2): `execution.research.question`, `execution.researchMonitor.completeness` · **personas** (2): `personas.list.{gridView,listView}` · **underlag** (2): `underlag.rootBreadcrumb`, `underlag.previewTabPdf`
- **1 var:** `anchorSets.pool.sourceManual`, `dashboard.title`, `expertgranskning.page.openResearch`, `help.subtitle`, `messages.workshop.imagePickPlaceholder`, `playground.image.loadingPersonas`, `tools.kunder.title`

> Extra exempel på nyckel som blir död först när §5b städas: `runs.feed.copyAttempt`/`runs.feed.copied` används bara av `CopyAttemptButton`.

---

## 9. Död CSS i `frontend/src/styles/admin-runs.css` (Verdict A/B)

37 regelblock (36 unika selektorer + en duplicerad `.mono`) vars samtliga klassnamn saknar förekomst i `.tsx/.ts/.html` (och som inte är dynamiskt byggda). `index.css` har 0 döda regler.

| Rad(er) | Selektor(er) | Verdict | Förslag |
|---|---|---|---|
| 291, 533 | `.mono` **definierad två gånger** (identisk deklaration) | A | Ta bort ena kopian |
| 536–537 | `.head-row-compact`, `.head-row-compact h1` | A | Ta bort |
| 621–623 | `.tl-interview-btn`, `.tl-interview-btn.has-items`, `.tl-interview-badge` | A | Ta bort (timeline-intervju-UI borta) |
| 656–661 | `.inj-link-row`, `.inj-link-row input`, `.inj-fetch-btn`, `.inj-fetch-btn:disabled`, `.inj-fetching`, `.inj-fetching .spin` | A | Ta bort (injektions-UI borta) |
| 685–687 | `.rounds-dots`, `.rd-dot`, `.rd-dot.on` | A | Ta bort |
| 710–712 | `.branch-cta`, `.branch-link`, `.branch-link:hover` | A | Ta bort |
| 754–755 | `.preflight-link`, `.preflight-link:hover` | A | Ta bort |
| 958 | `.entry-grid-2` | A | Ta bort |
| 986–993 | `.batch-summary`, `.bs-item` (+`b`), `.bs-item .warn`, `.compose-actions`, `.compose-actions-left` | A | Ta bort |
| 1001 | `.pcard-grid` | A | Ta bort |
| 1015–1020 | `.confirm-card` (+`.inner`,`.n`,`.rows` m.fl. döda descenders) | A | Ta bort |
| 1096–1097, 1146–1148 | `.p-transcript-msg`, `.p-transcript-msg .p-transcript-body`, `.p-transcript`, `.p-transcript p`, `.p-footnote` | A | Ta bort |
| 1232 | `.spinndoctor-widget--interview` | A | Ta bort |

**Ej döda (verifierat):** `.chat-md-h1..h4` byggs dynamiskt i `components/chat/ChatMarkdown.tsx:28` (`` `chat-md-${heading.tag}` ``) — falsk positiv, rör ej. `discard/inner/mono/warn/w3` förekommer som ord i backend-Python men inte som CSS-klasser (inte heller använda i frontend).

---

## 10. Döda assets

| Fil | Storlek | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| `frontend/src/assets/hero.png` | 13 KB | 0 referenser i hela `frontend/` (`.ts/.tsx/.css/.html`) | A | Ta bort (tracked) |
| `frontend/src/assets/vite.svg` | 9 KB | 0 referenser; `index.html` använder `/favicon.svg` från `public/` | A | Ta bort (tracked) |

---

## 11. word-addin (`word-addin/src/**`)

**Positivt:** 44 filer, 29 prod-reachabla — **0 oanvändbara filer**, **0 test-only moduler**, **0 oanvända npm-beroenden**, och **9/9** anropade endpoints finns i backend (`/expertgranskning/word-intent-interview`, `/word-jobs`, `/word-jobs/latest`, `/actions`, `/actions/{id}/claim|complete|unresolved|dismiss`, `/populations?kind=expert_panel`). Inga `new URL`-worklets eller dynamiska moduler som kan dölja död kod.

| Fynd | Antal | Bevis | Verdict | Förslag |
|---|---|---|---|---|
| Överexporterade symboler (intern användning) | 24 | 0 förekomster utanför egen fil; används internt | B | Ta bort `export`: `actionQueue.ts::{ACTION_PENDING,ACTION_APPLYING,ACTION_APPLIED,ACTION_UNRESOLVED,ACTION_DISMISSED,NewReviewBlock,ActionCardKind,actionCardKind,ActionCardModel}`, `office.ts::saveDocId`, `resume.ts::{ReviewStartPlan,FinishedJobView}`, `types.ts::{WordTaskType,WordExpertStrategy,WordActionSource,WatchReplay,WatchCreated,WatchUpdated,WatchFinished,WatchProgress}`, `watch.ts::WatchAction`, `word/anchors.ts::sameWordSession`, `word/executeWordAction.ts::WordActionKind`, `i18n/messages.ts::LOCALES` |
| Helt död typ | 1 | 0 träffar ens i egen fil förutom definitionen | A | `lib/word/anchors.ts:19::WordAnchorStatus` — ta bort |
| Döda i18n-nycklar (sv+en) | 7 | 0 referenser i någon `.ts/.tsx` (inkl. tester); paritet sv/en = 78/78 | A | `tokenSaved`, `interviewStart`, `statusConnecting`, `inserted`, `appliedSummary`, `unplacedSummary`, `applicationSummary` → ta bort i båda katalogerna |
| Manifest/`office-js`-koppling | — | `manifest`-referenser är inte kod; inga döda filer | — | — |
| Döda endpoints | 0 | 9/9 matchar backend-routers | — | — |

---

## 12. WIP-hänsyn (untracked/modifierat i feature-branchen)

`git status --porcelain -- frontend/src word-addin/src` = **51 untracked, 55 modifierade, 3 deleted** i frontend; word-addin är **helt clean**.

- Alla §3-filer är **tracked och orörda** i branchen → etablerad död kod, säker att ta bort.
- Följande fynd ligger i **modifierade** filer → behandla som **A/B med WIP-risk**, verifiera med feature-ägaren: `api/sme.ts::getSmeExpertTurn` (§5a), `components/ui/dialog.tsx::{DialogOverlay,DialogPortal,DialogTrigger}` (§7), `products/sme/workspaceChatLogic.ts::{isWorkspaceServerTool, workspaceClientToolNames, workspaceServerToolNames}` (§5b/§7), `products/sme/workspaceLocalSelection.ts::selectionsSameGeometry` (§7).
- 51 untracked filer (mest `products/sme/*`, `components/underlag/*`, `api/documentIngestBatches.ts`, `lib/sourceKind.ts`, `lib/uploadForm.ts`) är **ny WIP** — inga flaggas som obsoleta; de är alla reachabla från entry.
- `frontend/mockup/extracted/**` är enligt AGENTS.md visuell källa — **inte** auditerad som obsolet.

---

## 13. Topp-15 — prioriterad åtgärdslista

| # | Fynd | Omfattning | Verdict | Rekommenderad åtgärd |
|---|---|---|---|---|
| 1 | Verdict-calibration-klustret: `ReportVerdictCalibrationPanel.tsx` + `api/reports.ts::{getVerdictCalibration,saveVerdictCalibration,VerdictCalibration}` + 17 `reports.verdictCalibration.*`-nycklar | 175 rader + 3 symboler + 17 nycklar | A | Beslut med backend: antingen koppla in panelen i `ReportPage` eller ta bort hela klustret (backend-endpoints finns kvar) |
| 2 | DD-sourcing-klustret: `DdSourcingCriteriaFields.tsx` + `DdResearchAppointmentsTable.tsx` + `api/dd.ts::{defaultDdCriteria,searchDdSourcing,runDdCampaignSourcing,DdSourcingCriteria,DdResultatFilter}` + 12 `dd.sourcing.*`/`dd.panel.researchAppointment*`-nycklar | 152 rader + 5 symboler + 12 nycklar | A | Ta bort frontend-delen; backend `/dd/sourcing/*` lever kvar — dokumentera som övergiven yta |
| 3 | `lib/ddExpertRoles.ts` duplicerar `lib/expertKey.ts::expertRoleKey` — och **ingen** av dem används i prod (bara test) | 28 rader / 2 filer + 1 test | A | Ta bort `ddExpertRoles.ts`; avgör om `expertKey.ts` ska användas i DD-flödet eller tas bort med sitt test |
| 4 | `pages/PlaceholderPage.tsx` | 24 rader | A | Ta bort (oanvänd + hårdkodad svenska, bryter i18n-policyn) |
| 5 | 14 API-wrappers utan anropare | ~90 rader | A | Ta bort wrappers; endpoints finns kvar i backend så ingen backend-ändring krävs |
| 6 | 163 bekräftat döda i18n-nycklar | ~163 rader × 2 kataloger | A/B | Städa sektionsvis; börja med hela namespace: `configurations.editor.*`, `runs.live/results/interview`, `rattsunderlag.*`, `feedback.col*`, `experts.list.column*`, `bolag.nav.*`, `config.page.*` |
| 7 | 144 C-risk-i18n-nycklar under dynamiska prefix | 144 | C | **Radera inte** utan att först granska de 11 dynamiska byggena (särskilt `voiceWorkspaceChat` 76 st) |
| 8 | 30 transitivt döda i18n-nycklar | 30 | A | Ta bort i samma commit som #1/#2 |
| 9 | `CopyAttemptButton` + `formatAttemptForClipboard` (död kopia av fungerande `CopyFeedTextButton`) | ~70 rader | A | Ta bort båda; verifiera att `runs.feed.copyAttempt`/`copied` då också kan gå |
| 10 | `data/runs.ts::{RUN_STATUS_LABEL,extractDomain,looksLikeVideo}` + `data/library.ts::FP_DETAIL_LABELS` | ~25 rader | A | Ta bort; `RUN_STATUS_LABEL` är ersatt av `t("runs.status.*")` |
| 11 | 36 döda CSS-regler + `.mono`-dubblett i `admin-runs.css` | ~40 rader | A | Ta bort; verifiera visuellt att inga gamla vyer använder dem |
| 12 | `modules/moduleRegistry.ts::{MODULE_IDS,getModule}` + 39 överexporterade symboler | 41 `export`-nycklar | B | Ta bort `export`-nyckelordet (behåll kod); `MODULE_IDS`/`getModule` kan tas bort helt |
| 13 | `products/sme/smeTurnRecovery.ts` — prod-kod som bara testas | 44 rader + test | A/B | Koppla in i återhämtningsflödet eller ta bort kod + test |
| 14 | `frontend/src/assets/{hero.png,vite.svg}` | 22 KB | A | Ta bort |
| 15 | word-addin: 25 överexporter + 7 döda i18n-nycklar (`tokenSaved`, `interviewStart`, `statusConnecting`, `inserted`, `appliedSummary`, `unplacedSummary`, `applicationSummary`) | 32 | B | Ta bort `export`/nycklarna; i övrigt är word-addin rent |

---

## 14. Vad som INTE är obsolet (positiva kontroller)

- **Alla 43 sidor** i `pages/` nås från `App.tsx` (69 route-paths); 0 döda routes. Alla modul-`navItems`/`homePath` (`/bolag/campaigns`, `/bolag/experter`, …) matchar faktiska routes.
- **Alla 22 npm-beroenden** i `frontend/package.json` importeras (0 oanvända; `shadcn`, `tw-animate-css`, `@fontsource-variable/geist` används via CSS/index.html).
- **Alla `api/*.ts`-moduler** är importerade; 0 oanvända API-moduler (endast enskilda funktioner, §5a).
- **Alla `data/`, `auth/`, `modules/`, `i18n/`-filer** nås.
- Dynamiska referenser som medvetet **inte** flaggats: worklets/workers (`new URL`), `React.lazy`, `import.meta.glob` (finns ej i repot), i18n-mallsträngar, Tailwind-klasser, `MODULE_REGISTRY`/`frontendEntry`.

---

## 15. Begränsningar

- Analysen är statisk: en export som bara nås via en framtida route/feature (planerad men ej inkopplad) kan se död ut. Därför Verdict A/B/C-skalan och WIP-markeringarna i §12.
- `tsc -b` (noUnusedLocals/`noUnusedParameters`) fångar lokala oanvända variabler men **inte** oanvända filer/exporter/nycklar — därför denna manuella/scriptade analys. Ingen build kördes (read-only-uppdraget).
- i18n-räkningen söker literal förekomster av hela nyckeln; en nyckel som byggs via variabel kan aldrig hittas statiskt (därav C-kategorin).
- Testfiler ingår som konsumenter i räkningen (en export som bara testas räknas som "test-only", inte "helt död") — detaljerna hör test-auditen till.

**Rådata/script:** `/tmp/obsolete-audit/fe/{wa_graph.py,exports.py,i18n.mjs,deps.mjs,frontend_exports.json,prod_exports2.json,final_dead_exports.json,i18n.json,i18n_sections.json,wa_dead.json}`.
