import type { AttemptStatus, EvidenceItemStatus, EvidenceSetStatus } from "@/api/execution"
import type { MessageKey } from "@/i18n"

export function isAttemptStatus(value: string): value is AttemptStatus {
  return (
    value === "created" ||
    value === "researching" ||
    value === "ready" ||
    value === "running" ||
    value === "completed" ||
    value === "failed"
  )
}

export function attemptStatusLabelKey(status: AttemptStatus): MessageKey {
  switch (status) {
    case "created":
      return "execution.attempt.status.created"
    case "researching":
      return "execution.attempt.status.researching"
    case "ready":
      return "execution.attempt.status.ready"
    case "running":
      return "execution.attempt.status.running"
    case "completed":
      return "execution.attempt.status.completed"
    case "failed":
      return "execution.attempt.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function attemptStatusTagClass(status: string): string {
  if (!isAttemptStatus(status)) return "status-tag"
  switch (status) {
    case "created":
      return "status-tag draft"
    case "researching":
    case "running":
      return "status-tag running"
    case "ready":
    case "completed":
      return "status-tag done"
    case "failed":
      return "status-tag failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function isEvidenceItemStatus(value: string): value is EvidenceItemStatus {
  return value === "found" || value === "not_found" || value === "error"
}

export function evidenceItemStatusLabelKey(status: EvidenceItemStatus): MessageKey {
  switch (status) {
    case "found":
      return "execution.evidence.status.found"
    case "not_found":
      return "execution.evidence.status.notFound"
    case "error":
      return "execution.evidence.status.error"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function evidenceItemStatusTagClass(status: string): string {
  if (!isEvidenceItemStatus(status)) return "status-tag"
  switch (status) {
    case "found":
      return "status-tag done"
    case "not_found":
      return "status-tag draft"
    case "error":
      return "status-tag failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function isEvidenceSetStatus(value: string): value is EvidenceSetStatus {
  return value === "building" || value === "frozen" || value === "failed"
}

export function evidenceSetStatusLabelKey(status: EvidenceSetStatus): MessageKey {
  switch (status) {
    case "building":
      return "execution.evidence.setBuilding"
    case "frozen":
      return "execution.evidence.setFrozen"
    case "failed":
      return "execution.evidence.setFailed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function attemptTypeLabelKey(attemptType: string): MessageKey | null {
  switch (attemptType) {
    case "generic_panel":
      return "execution.attempt.type.genericPanel"
    case "structured_scoring":
      return "execution.attempt.type.structuredScoring"
    case "word_review":
      return "execution.attempt.type.wordReview"
    default:
      return null
  }
}
