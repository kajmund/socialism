export type GenericPanelExpertSlot = {
  slot_id: string
  label: string
  profile: string
}

export type GenericPanelFields = {
  topic: string
  brief: string
  max_rounds: number | null
  expert_slots: GenericPanelExpertSlot[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function readSlots(value: unknown): GenericPanelExpertSlot[] {
  if (!Array.isArray(value)) return []
  const slots: GenericPanelExpertSlot[] = []
  for (const raw of value) {
    const row = asRecord(raw)
    if (row == null) continue
    const slotId = readString(row.slot_id)
    const label = readString(row.label)
    if (!slotId && !label) continue
    slots.push({
      slot_id: slotId,
      label,
      profile: readString(row.profile),
    })
  }
  return slots
}

export function extractGenericPanelFields(
  configuration: Record<string, unknown>,
  input: Record<string, unknown>,
): GenericPanelFields {
  const nested = asRecord(configuration.panel)
  const raw = nested ?? configuration
  const topic =
    readString(raw.topic) || readString(input.topic) || readString(input.question)
  const brief = readString(raw.brief) || readString(input.brief)
  const maxRounds = raw.max_rounds
  return {
    topic,
    brief,
    max_rounds: typeof maxRounds === "number" && Number.isFinite(maxRounds) ? maxRounds : null,
    expert_slots: readSlots(raw.expert_slots),
  }
}

export function researchNeedsFromSnapshot(
  snapshot: Record<string, unknown> | null,
): Array<{
  id: string
  question: string
  why_needed: string
  requested_by: string[]
  source_types: string[]
}> | null {
  if (snapshot == null) return []
  const needs = snapshot.needs
  if (!Array.isArray(needs)) return null
  return needs.flatMap((raw, index) => {
    const row = asRecord(raw)
    if (row == null) return []
    const requested = Array.isArray(row.requested_by)
      ? row.requested_by.filter((item): item is string => typeof item === "string")
      : []
    const sourceTypes = Array.isArray(row.source_types)
      ? row.source_types.filter((item): item is string => typeof item === "string")
      : []
    return [
      {
        id: readString(row.id) || `need-${index + 1}`,
        question: readString(row.question),
        why_needed: readString(row.why_needed),
        requested_by: requested,
        source_types: sourceTypes,
      },
    ]
  })
}

export function caseIdFromContext(context: Record<string, unknown>): string | null {
  const value = context.case_id
  return typeof value === "string" && value.trim() ? value : null
}
