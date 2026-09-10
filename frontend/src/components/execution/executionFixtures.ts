import type {
  AttemptResult,
  EvidenceSet,
  EvidenceSetItem,
  ExecutionAttempt,
  ExecutionRun,
} from "@/api/execution"

export const fixtureRun: ExecutionRun = {
  id: "run-1",
  customer_id: 1,
  module: "dd",
  title: "Skattesats",
  context: { case_id: "case-1" },
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T12:00:00Z",
}

function attempt(partial: Partial<ExecutionAttempt> & Pick<ExecutionAttempt, "id" | "status">): ExecutionAttempt {
  return {
    run_id: "run-1",
    parent_attempt_id: null,
    attempt_type: "generic_panel",
    configuration_snapshot: {
      topic: "Vad gäller skattesatsen?",
      brief: "Kommunal skattesats.",
      max_rounds: 1,
      expert_slots: [{ slot_id: "legal", label: "Jurist", profile: "Skatt" }],
    },
    input_snapshot: { topic: "Vad gäller skattesatsen?" },
    research_plan_snapshot: {
      needs: [
        {
          id: "research_1",
          question: "Vad gäller skattesatsen?",
          why_needed: "behövs för bedömning",
          requested_by: ["legal"],
          source_types: ["case_knowledge"],
        },
      ],
    },
    evidence: null,
    result: null,
    created_at: "2026-04-01T10:00:00Z",
    started_at: null,
    completed_at: null,
    ...partial,
  }
}

export const fixtureItem = (
  partial: Partial<EvidenceSetItem> & Pick<EvidenceSetItem, "id" | "ordinal" | "status">,
): EvidenceSetItem => ({
  evidence_set_id: "set-1",
  research_need_id: "research_1",
  original_evidence_id: partial.id,
  source_type: "case_knowledge",
  title: `Titel ${partial.id}`,
  excerpt: `Utdrag ${partial.id}`,
  locator: `p${partial.ordinal}`,
  source_id: "doc-brief",
  source_url: "https://example.test/brief.pdf",
  provider: "supabase",
  score: 0.9,
  provenance: { document_id: "doc-brief", version: "3" },
  retrieved_at: "2026-04-01T11:00:00Z",
  content_hash: `hash-${partial.id}`,
  ...partial,
})

export const fixtureEvidence: EvidenceSet = {
  id: "set-1",
  run_id: "run-1",
  created_from_attempt_id: "attempt-a",
  status: "frozen",
  created_at: "2026-04-01T10:30:00Z",
  frozen_at: "2026-04-01T10:45:00Z",
  items: [
    fixtureItem({ id: "item-e1", ordinal: 0, status: "found", title: "Kommunens skattesats" }),
    fixtureItem({ id: "item-e2", ordinal: 1, status: "found", title: "Jämförelse 2024" }),
    fixtureItem({ id: "item-e3", ordinal: 2, status: "found", title: "Policy" }),
  ],
}

export const mixedEvidence: EvidenceSet = {
  ...fixtureEvidence,
  items: [
    fixtureItem({ id: "item-found", ordinal: 2, status: "found", title: "Hittad sist" }),
    fixtureItem({ id: "item-missing", ordinal: 0, status: "not_found", title: "Saknas först" }),
    fixtureItem({ id: "item-error", ordinal: 1, status: "error", title: "Fel i mitten" }),
  ],
}

export const fixtureResult: AttemptResult = {
  id: "result-1",
  result_type: "generic_panel",
  schema_version: "1",
  payload: {
    schema_version: "1",
    protocol: "generic_panel",
    summary: "Skattesatsen är 32%.",
    claims: [
      {
        claim_id: "c1",
        claim: "Kommunalskatten är 32%.",
        evidence: "Fryst underlag [E1].",
        judgment: "Bedömd slutsats.",
        score: null,
        dissensus: false,
        evidence_refs: ["E1"],
      },
    ],
    unanswered: ["Svensk lag kunde inte hämtas."],
  },
  evidence_refs: {
    E1: { item_id: "item-e1", original_evidence_id: "item-e1", ordinal: 0 },
  },
  panel_session_id: "panel-1",
  created_at: "2026-04-01T11:30:00Z",
}

export const fixtureAttemptA = attempt({
  id: "attempt-a",
  status: "completed",
  created_at: "2026-04-01T10:00:00Z",
  completed_at: "2026-04-01T11:30:00Z",
  evidence: {
    evidence_set_id: "set-1",
    status: "frozen",
    found_count: 3,
    not_found_count: 0,
    error_count: 0,
  },
  result: fixtureResult,
})

export const fixtureAttemptB = attempt({
  id: "attempt-b",
  status: "ready",
  created_at: "2026-04-01T11:40:00Z",
  evidence: {
    evidence_set_id: "set-1",
    status: "frozen",
    found_count: 3,
    not_found_count: 0,
    error_count: 0,
  },
})

export const fixtureAttemptC = attempt({
  id: "attempt-c",
  status: "failed",
  created_at: "2026-04-01T12:00:00Z",
  parent_attempt_id: "attempt-a",
  completed_at: "2026-04-01T12:10:00Z",
  evidence: {
    evidence_set_id: "set-1",
    status: "frozen",
    found_count: 3,
    not_found_count: 0,
    error_count: 0,
  },
})

export const fixtureAttempts = [fixtureAttemptA, fixtureAttemptB, fixtureAttemptC]
