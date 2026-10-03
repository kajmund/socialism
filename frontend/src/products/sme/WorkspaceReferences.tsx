import type { SourceReference } from "@/api/workspaces"
import { useLocale } from "@/i18n"

export function WorkspaceReferences({ ids, references, onOpen }: { ids: string[]; references: SourceReference[]; onOpen: (id: string) => void }) {
  const { t } = useLocale()
  return <span className="inline-flex flex-wrap gap-1">{ids.map((id) => {
    const reference = references.find((row) => row.reference_id === id)
    if (!reference) return null
    return <button type="button" key={id} className="inline-grid min-w-5 place-items-center rounded bg-db-ink-950 px-1 text-xs font-semibold text-db-gold-500 ring-offset-2 focus-visible:ring-2 focus-visible:ring-db-gold-500" aria-label={t("workspaceChat.source", { number: reference.number })} title={reference.title} onClick={(event) => { event.stopPropagation(); onOpen(id) }}>{reference.number}</button>
  })}</span>
}
