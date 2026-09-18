import { useState } from "react"
import type { ExpertMemory } from "@/api/expertMemory"
import { CachedAuthImage } from "@/components/chat/CachedAuthImage"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

const SOURCE_KEYS: Record<string, MessageKey> = {
  persona_chat: "experts.memory.sourcePersonaChat",
  panel_chat: "experts.memory.sourcePanelChat",
  intent_interview: "experts.memory.sourceIntent",
  word_findings: "experts.memory.sourceWord",
  research_receipt: "experts.memory.sourceResearch",
}

function sourceLabel(source: string, t: (key: MessageKey) => string): string {
  const key = SOURCE_KEYS[source]
  return key ? t(key) : source || t("common.emDash")
}

export function ExpertMemoryLog({
  memories,
  empty,
  showExpert = false,
  customerName,
  formatWhen,
  onSave,
  onDelete,
}: {
  memories: ExpertMemory[]
  empty: string
  showExpert?: boolean
  customerName?: (id: number | null) => string
  formatWhen: (iso: string) => string
  onSave?: (row: ExpertMemory, text: string) => Promise<ExpertMemory>
  onDelete?: (row: ExpertMemory) => Promise<void>
}) {
  const { t } = useLocale()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rowError, setRowError] = useState<string | null>(null)

  if (memories.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>
  }

  const editable = Boolean(onSave || onDelete)

  async function save(row: ExpertMemory) {
    if (!onSave) return
    const text = draft.trim()
    if (!text) {
      setRowError(t("experts.memory.emptyText"))
      return
    }
    setBusyId(row.id)
    setRowError(null)
    try {
      await onSave(row, text)
      setEditingId(null)
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : t("experts.memory.saveError"))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(row: ExpertMemory) {
    if (!onDelete) return
    setBusyId(row.id)
    setRowError(null)
    try {
      await onDelete(row)
      setConfirmId(null)
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : t("experts.memory.deleteError"))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <ul className="space-y-3">
      {memories.map((row) => {
        const when = formatWhen(row.updated_at || row.created_at)
        const kund = customerName?.(row.customer_id)
        const rowKey = row.id || `${row.expert_id}-${row.text}`
        const editing = editingId === row.id
        const confirming = confirmId === row.id
        const busy = busyId === row.id
        return (
          <li
            key={rowKey}
            className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2.5"
          >
            <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
              {showExpert ? (
                <span className="font-medium text-[color:var(--text-body)]">
                  {row.expert_name || row.expert_id || t("common.emDash")}
                </span>
              ) : null}
              {kund ? <span>{kund}</span> : null}
              <span>{sourceLabel(row.source, t)}</span>
              {when ? <span>{when}</span> : null}
            </div>
            {row.image_sha256 ? (
              <CachedAuthImage
                className="mb-2 max-h-40 rounded"
                sha256={row.image_sha256}
                alt={t("experts.memory.imageAlt")}
              />
            ) : null}
            {editing ? (
              <textarea
                className="mb-2 w-full rounded-md border border-[color:var(--border-hairline)] bg-background px-2 py-1.5 text-[13px] leading-snug"
                rows={3}
                value={draft}
                disabled={busy}
                onChange={(e) => setDraft(e.target.value)}
              />
            ) : (
              <p className="text-[13px] leading-snug text-[color:var(--text-body)]">{row.text}</p>
            )}
            {editable && row.id ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {editing ? (
                  <>
                    <AdminButton
                      variant="primary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void save(row)}
                    >
                      {t("experts.memory.save")}
                    </AdminButton>
                    <AdminButton
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        setEditingId(null)
                        setRowError(null)
                      }}
                    >
                      {t("experts.memory.cancel")}
                    </AdminButton>
                  </>
                ) : confirming ? (
                  <>
                    <span className="text-xs text-muted-foreground">
                      {t("experts.memory.confirmDelete")}
                    </span>
                    <AdminButton
                      variant="primary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void remove(row)}
                    >
                      {t("experts.memory.delete")}
                    </AdminButton>
                    <AdminButton
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => setConfirmId(null)}
                    >
                      {t("experts.memory.cancel")}
                    </AdminButton>
                  </>
                ) : (
                  <>
                    {onSave ? (
                      <AdminButton
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        aria-label={t("experts.memory.editAria")}
                        onClick={() => {
                          setEditingId(row.id)
                          setDraft(row.text)
                          setConfirmId(null)
                          setRowError(null)
                        }}
                      >
                        {t("experts.memory.edit")}
                      </AdminButton>
                    ) : null}
                    {onDelete ? (
                      <AdminButton
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        aria-label={t("experts.memory.deleteAria")}
                        onClick={() => {
                          setConfirmId(row.id)
                          setEditingId(null)
                          setRowError(null)
                        }}
                      >
                        {t("experts.memory.delete")}
                      </AdminButton>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}
            {rowError && (editing || confirming) ? (
              <p className="mt-2 text-xs text-destructive" role="alert">
                {rowError}
              </p>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
