import { api } from "@/lib/api"
import type { AnchorKind, AnchorLocale } from "@/api/anchorSets"

export type LabelVocabularyEntry = {
  key: string
  label: string
}

export type LabelVocabulary = {
  kind: AnchorKind
  locale: AnchorLocale
  entries: LabelVocabularyEntry[]
  usage: Record<string, number>
  updated_at: string
}

export type LabelVocabularyRenameOp = {
  key: string
  new_label: string
}

export type LabelVocabularyAddOp = {
  label: string
}

export type LabelVocabularyRemoveOp = {
  key: string
}

export type LabelVocabularyPatch = {
  rename?: LabelVocabularyRenameOp[]
  add?: LabelVocabularyAddOp[]
  remove?: LabelVocabularyRemoveOp[]
}

export function listLabelVocabularies(params?: {
  kind?: AnchorKind
  locale?: AnchorLocale
}): Promise<LabelVocabulary[]> {
  return api.get<LabelVocabulary[]>("/label-vocabularies", params)
}

export function getLabelVocabulary(
  kind: AnchorKind,
  locale: AnchorLocale,
): Promise<LabelVocabulary> {
  return api.get<LabelVocabulary>(`/label-vocabularies/${kind}/${locale}`)
}

export function patchLabelVocabulary(
  kind: AnchorKind,
  locale: AnchorLocale,
  body: LabelVocabularyPatch,
): Promise<LabelVocabulary> {
  return api.patch<LabelVocabulary>(`/label-vocabularies/${kind}/${locale}`, body)
}
