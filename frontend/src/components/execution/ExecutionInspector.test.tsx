import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { LocaleProvider } from "@/i18n"

import { ExecutionInspector, ExecutionLoadMessage } from "./ExecutionInspector"
import { resolveEvidenceRef } from "./evidenceRefs"
import {
  fixtureAttemptA,
  fixtureAttemptB,
  fixtureAttemptC,
  fixtureAttempts,
  fixtureEvidence,
  fixtureResult,
  fixtureRun,
  mixedEvidence,
} from "./executionFixtures"

function renderInspector(args: {
  selected?: typeof fixtureAttemptA
  evidence?: typeof fixtureEvidence | null
  result?: typeof fixtureResult | null
  evidenceError?: string | null
  resultError?: string | null
  attempts?: typeof fixtureAttempts
}) {
  return renderToStaticMarkup(
    <LocaleProvider>
      <ExecutionInspector
        run={fixtureRun}
        attempts={args.attempts ?? fixtureAttempts}
        selectedAttempt={args.selected ?? fixtureAttemptA}
        evidence={args.evidence === undefined ? fixtureEvidence : args.evidence}
        evidenceError={args.evidenceError}
        result={args.result === undefined ? fixtureResult : args.result}
        resultError={args.resultError}
        onSelectAttempt={() => undefined}
      />
    </LocaleProvider>,
  )
}

describe("ExecutionInspector", () => {
  it("loads a run and its attempts", () => {
    const html = renderInspector({})
    expect(html).toContain("Skattesats")
    expect(html).toContain("case-1")
    expect(html).toContain("Attempt 1")
    expect(html).toContain("Attempt 2")
    expect(html).toContain("Attempt 3")
    expect(html).toContain("Klar")
    expect(html).toContain("Redo")
    expect(html).toContain("Misslyckad")
  })

  it("shows selected attempt detail with snapshots and research plan", () => {
    const html = renderInspector({ selected: fixtureAttemptA })
    expect(html).toContain("data-attempt-detail=\"attempt-a\"")
    expect(html).toContain("Vad gäller skattesatsen?")
    expect(html).toContain("Kommunal skattesats.")
    expect(html).toContain("Jurist")
    expect(html).toContain("behövs för bedömning")
    expect(html).toContain("case_knowledge")
  })

  it("shows an empty evidence state when the attempt has none", () => {
    const html = renderInspector({
      selected: fixtureAttemptB,
      evidence: null,
      result: null,
    })
    expect(html).toContain("Inget evidence är sparat för det här attemptet.")
    expect(html).toContain("Inget resultat är sparat för det här attemptet.")
    expect(html).not.toContain("data-execution-state=\"error\"")
  })

  it("shows section errors without hiding the rest of the attempt", () => {
    const html = renderInspector({
      selected: fixtureAttemptA,
      evidence: null,
      result: null,
      evidenceError: "Kunde inte hämta evidence.",
      resultError: "Kunde inte hämta resultatet.",
    })
    expect(html).toContain('data-section-error="evidence"')
    expect(html).toContain('data-section-error="result"')
    expect(html).toContain("Kunde inte hämta evidence.")
    expect(html).toContain("Kunde inte hämta resultatet.")
    expect(html).not.toContain("Inget evidence är sparat för det här attemptet.")
    expect(html).not.toContain("Inget resultat är sparat för det här attemptet.")
    expect(html).toContain("Vad gäller skattesatsen?")
    expect(html).not.toContain('data-execution-state="error"')
  })

  it("renders evidence in persisted ordinal order", () => {
    const html = renderInspector({ evidence: mixedEvidence, result: null })
    const missing = html.indexOf("Saknas först")
    const error = html.indexOf("Fel i mitten")
    const found = html.indexOf("Hittad sist")
    expect(missing).toBeGreaterThan(-1)
    expect(error).toBeGreaterThan(missing)
    expect(found).toBeGreaterThan(error)
  })

  it("keeps found, not_found and error visually distinct", () => {
    const html = renderInspector({ evidence: mixedEvidence, result: null })
    expect(html).toContain("data-evidence-status=\"found\"")
    expect(html).toContain("data-evidence-status=\"not_found\"")
    expect(html).toContain("data-evidence-status=\"error\"")
    expect(html).toContain("status-tag done")
    expect(html).toContain("status-tag draft")
    expect(html).toContain("status-tag failed")
    expect(html).toContain("Hittad")
    expect(html).toContain("Ej hittad")
    expect(html).toContain("Fel")
  })

  it("renders generic_panel summary, claims and unanswered", () => {
    const html = renderInspector({})
    expect(html).toContain("Skattesatsen är 32%.")
    expect(html).toContain("Kommunalskatten är 32%.")
    expect(html).toContain("Svensk lag kunde inte hämtas.")
    expect(html).toContain("Sammanfattning")
    expect(html).toContain("Påståenden")
    expect(html).toContain("Obesvarat")
  })

  it("resolves E1 to the matching evidence card", () => {
    const html = renderInspector({})
    expect(html).toContain("data-evidence-ref=\"E1\"")
    expect(html).toContain("id=\"execution-evidence-item-e1\"")
    expect(resolveEvidenceRef("E1", fixtureEvidence.items, fixtureResult.evidence_refs)?.id).toBe(
      "item-e1",
    )
  })

  it("keeps an unknown evidence ref visible without crashing", () => {
    const result = {
      ...fixtureResult,
      payload: {
        ...fixtureResult.payload,
        claims: [
          {
            claim_id: "c-unknown",
            claim: "Okänd källa",
            evidence: "Pekar på [E99].",
            judgment: "Osäkert.",
            score: null,
            dissensus: false,
            evidence_refs: ["E99"],
          },
        ],
      },
    }
    const html = renderInspector({ result })
    expect(html).toContain("data-unresolved=\"true\"")
    expect(html).toContain("[E99]")
    expect(html).toContain("Okänd referens")
    expect(resolveEvidenceRef("E99", fixtureEvidence.items, result.evidence_refs)).toBeNull()
  })

  it("shows parent attempt lineage", () => {
    const html = renderInspector({ selected: fixtureAttemptC })
    expect(html).toContain("Baserad på Attempt 1")
  })

  it("keeps historical evidence visible on a failed attempt", () => {
    const html = renderInspector({ selected: fixtureAttemptC, evidence: fixtureEvidence })
    expect(html).toContain("Misslyckad")
    expect(html).toContain("Kommunens skattesats")
    expect(html).toContain("[E1]")
    expect(html).toContain("Vad gäller skattesatsen?")
  })

  it("falls back to structured JSON for an unknown result type", () => {
    const html = renderInspector({
      result: {
        ...fixtureResult,
        result_type: "structured_scoring",
        payload: { score: 7, note: "okänd metod" },
      },
    })
    expect(html).toContain("Okänd resultattyp")
    expect(html).toContain("structured_scoring")
    expect(html).toContain("okänd metod")
  })

  it("renders 403 and 404 as dedicated states, not as empty evidence errors", () => {
    const forbidden = renderToStaticMarkup(
      <LocaleProvider>
        <ExecutionLoadMessage state="forbidden" />
      </LocaleProvider>,
    )
    const missing = renderToStaticMarkup(
      <LocaleProvider>
        <ExecutionLoadMessage state="not_found" />
      </LocaleProvider>,
    )
    expect(forbidden).toContain("data-execution-state=\"forbidden\"")
    expect(forbidden).toContain("Du har inte behörighet")
    expect(missing).toContain("data-execution-state=\"not_found\"")
    expect(missing).toContain("Körningen hittades inte.")
  })
})
