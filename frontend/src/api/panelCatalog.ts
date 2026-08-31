import { api, ApiError } from "@/lib/api"

export type PanelSubQuestion = {
  id: number
  module: string
  key: string
  label: string
  sort_order: number
  active: boolean
  created_at: string
  updated_at: string
}

export type PanelExpertProfile = {
  id: number
  module: string
  key: string
  name: string
  description: string
  kompetensomrade: string
  radgivningsstil: string
  yrkesbakgrund: string
  professionell_anekdot: string
  sort_order: number
  active: boolean
  created_at: string
  updated_at: string
}

export function listPanelSubQuestions(
  module: string,
  includeInactive = true,
): Promise<PanelSubQuestion[]> {
  return api.get<PanelSubQuestion[]>("/panel/sub-questions", {
    module,
    include_inactive: includeInactive,
  })
}

export function createPanelSubQuestion(body: {
  module: string
  key: string
  label: string
  sort_order?: number
  active?: boolean
}): Promise<PanelSubQuestion> {
  return api.post<PanelSubQuestion>("/panel/sub-questions", body)
}

export function updatePanelSubQuestion(
  id: number,
  body: { label?: string; sort_order?: number; active?: boolean },
): Promise<PanelSubQuestion> {
  return api.patch<PanelSubQuestion>(`/panel/sub-questions/${id}`, body)
}

export function listPanelExpertProfiles(
  module: string,
  includeInactive = true,
): Promise<PanelExpertProfile[]> {
  return api.get<PanelExpertProfile[]>("/panel/expert-profiles", {
    module,
    include_inactive: includeInactive,
  })
}

export function createPanelExpertProfile(body: {
  module: string
  key?: string
  name: string
  description?: string
  kompetensomrade?: string
  radgivningsstil?: string
  yrkesbakgrund?: string
  professionell_anekdot?: string
  sort_order?: number
  active?: boolean
}): Promise<PanelExpertProfile> {
  return api.post<PanelExpertProfile>("/panel/expert-profiles", body)
}

export function updatePanelExpertProfile(
  id: number,
  body: {
    name?: string
    description?: string
    kompetensomrade?: string
    radgivningsstil?: string
    yrkesbakgrund?: string
    professionell_anekdot?: string
    sort_order?: number
    active?: boolean
  },
): Promise<PanelExpertProfile> {
  return api.patch<PanelExpertProfile>(`/panel/expert-profiles/${id}`, body)
}

export function isSortOrderConflict(err: unknown): boolean {
  return err instanceof ApiError && /sort order already used/i.test(err.message)
}

export function sortOrderInUse(
  rows: readonly { id: number; sort_order: number }[],
  drafts: Record<number, { sort_order: string }>,
  rowId: number,
  sortOrder: number,
): boolean {
  return rows.some((row) => {
    if (row.id === rowId) return false
    const raw = drafts[row.id]?.sort_order
    const other = raw !== undefined ? Number(raw) : row.sort_order
    return other === sortOrder
  })
}
