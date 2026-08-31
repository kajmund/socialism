import { useEffect, useState } from "react"
import {
  createPanelSubQuestion,
  deletePanelSubQuestion,
  isSortOrderConflict,
  listPanelSubQuestions,
  sortOrderInUse,
  updatePanelSubQuestion,
  type PanelSubQuestion,
} from "@/api/panelCatalog"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type PanelSubQuestionsEditorProps = {
  moduleId: string
}

export function PanelSubQuestionsEditor({ moduleId }: PanelSubQuestionsEditorProps) {
  const { t } = useLocale()
  const [rows, setRows] = useState<PanelSubQuestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | "new" | null>(null)
  const [drafts, setDrafts] = useState<Record<number, { label: string; sort_order: string }>>({})
  const [newKey, setNewKey] = useState("")
  const [newLabel, setNewLabel] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listPanelSubQuestions(moduleId, false)
      .then((data) => {
        if (cancelled) return
        setRows(data)
        setDrafts(
          Object.fromEntries(data.map((row) => [row.id, { label: row.label, sort_order: String(row.sort_order) }])),
        )
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("tools.panelCatalog.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [moduleId, t])

  function draftFor(row: PanelSubQuestion): { label: string; sort_order: string } {
    return drafts[row.id] ?? { label: row.label, sort_order: String(row.sort_order) }
  }

  async function saveRow(row: PanelSubQuestion) {
    const draft = draftFor(row)
    const sortOrder = Number(draft.sort_order)
    if (!draft.label.trim() || Number.isNaN(sortOrder)) {
      setError(t("tools.panelCatalog.invalidRow"))
      return
    }
    if (sortOrderInUse(rows, drafts, row.id, sortOrder)) {
      setError(t("tools.panelCatalog.duplicateSort"))
      return
    }
    setSavingId(row.id)
    setError(null)
    try {
      const updated = await updatePanelSubQuestion(row.id, {
        label: draft.label.trim(),
        sort_order: sortOrder,
      })
      setRows((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setDrafts((prev) => ({
        ...prev,
        [updated.id]: { label: updated.label, sort_order: String(updated.sort_order) },
      }))
    } catch (err: unknown) {
      setError(
        isSortOrderConflict(err)
          ? t("tools.panelCatalog.duplicateSort")
          : err instanceof ApiError
            ? err.message
            : t("common.saveError"),
      )
    } finally {
      setSavingId(null)
    }
  }

  async function removeRow(row: PanelSubQuestion) {
    setSavingId(row.id)
    setError(null)
    try {
      await deletePanelSubQuestion(row.id)
      setRows((prev) => prev.filter((item) => item.id !== row.id))
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[row.id]
        return next
      })
    } catch (err: unknown) {
      setError(
        err instanceof ApiError && /used in a run/i.test(err.message)
          ? t("tools.panelCatalog.removeInUse")
          : err instanceof ApiError
            ? err.message
            : t("common.saveError"),
      )
    } finally {
      setSavingId(null)
    }
  }

  async function addRow() {
    const key = newKey.trim()
    const label = newLabel.trim()
    if (!key || !label) {
      setError(t("tools.panelCatalog.needKeyAndLabel"))
      return
    }
    setSavingId("new")
    setError(null)
    try {
      const created = await createPanelSubQuestion({ module: moduleId, key, label })
      setRows((prev) => [...prev, created])
      setDrafts((prev) => ({
        ...prev,
        [created.id]: { label: created.label, sort_order: String(created.sort_order) },
      }))
      setNewKey("")
      setNewLabel("")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  if (loading) return <p className="muted">{t("tools.panelCatalog.loading")}</p>

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-medium">{t("tools.panelCatalog.subQuestionsTitle")}</h2>
      <p className="text-sm text-muted-foreground">{t("tools.panelCatalog.subQuestionsIntro")}</p>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-[color:var(--border-hairline)]">
              <th className="px-2 py-1.5 font-medium">{t("tools.panelCatalog.colKey")}</th>
              <th className="px-2 py-1.5 font-medium">{t("tools.panelCatalog.colLabel")}</th>
              <th className="px-2 py-1.5 font-medium">{t("tools.panelCatalog.colSort")}</th>
              <th className="px-2 py-1.5 font-medium">{t("tools.panelCatalog.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const draft = draftFor(row)
              return (
                <tr key={row.id} className="border-b border-[color:var(--border-hairline)] align-middle">
                  <td className="px-2 py-1.5 font-mono text-xs">{row.key}</td>
                  <td className="px-2 py-1.5">
                    <input
                      className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                      value={draft.label}
                      aria-label={t("tools.panelCatalog.colLabel")}
                      onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [row.id]: { ...draft, label: event.target.value },
                        }))
                      }
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      className="w-20 rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                      value={draft.sort_order}
                      inputMode="numeric"
                      aria-label={t("tools.panelCatalog.colSort")}
                      onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [row.id]: { ...draft, sort_order: event.target.value },
                        }))
                      }
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex flex-wrap gap-2">
                      <AdminButton
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={savingId === row.id}
                        onClick={() => void saveRow(row)}
                      >
                        {savingId === row.id ? t("common.saving") : t("common.save")}
                      </AdminButton>
                      <AdminButton
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={savingId === row.id}
                        onClick={() => void removeRow(row)}
                      >
                        {t("tools.panelCatalog.removeSubQuestion")}
                      </AdminButton>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void addRow()
        }}
      >
        <label className="text-sm">
          <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colKey")}</span>
          <input
            className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1 font-mono"
            value={newKey}
            onChange={(event) => setNewKey(event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colLabel")}</span>
          <input
            className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
          />
        </label>
        <AdminButton type="submit" variant="primary" size="sm" disabled={savingId === "new"}>
          {savingId === "new" ? t("common.saving") : t("tools.panelCatalog.addSubQuestion")}
        </AdminButton>
      </form>
    </div>
  )
}
