import { useEffect, useState } from "react"
import {
  createPanelExpertProfile,
  isSortOrderConflict,
  listPanelExpertProfiles,
  sortOrderInUse,
  updatePanelExpertProfile,
  type PanelExpertProfile,
} from "@/api/panelCatalog"
import { SuggestExpertsModal } from "@/components/tools/SuggestExpertsModal"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type PanelExpertProfilesEditorProps = {
  moduleId: string
}

type ProfileDraft = {
  name: string
  description: string
  kompetensomrade: string
  radgivningsstil: string
  yrkesbakgrund: string
  professionell_anekdot: string
  sort_order: string
}

function draftFromRow(row: PanelExpertProfile): ProfileDraft {
  return {
    name: row.name,
    description: row.description,
    kompetensomrade: row.kompetensomrade,
    radgivningsstil: row.radgivningsstil,
    yrkesbakgrund: row.yrkesbakgrund,
    professionell_anekdot: row.professionell_anekdot,
    sort_order: String(row.sort_order),
  }
}

const EMPTY_DRAFT: ProfileDraft = {
  name: "",
  description: "",
  kompetensomrade: "",
  radgivningsstil: "",
  yrkesbakgrund: "",
  professionell_anekdot: "",
  sort_order: "",
}

export function PanelExpertProfilesEditor({ moduleId }: PanelExpertProfilesEditorProps) {
  const { t } = useLocale()
  const [rows, setRows] = useState<PanelExpertProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | "new" | null>(null)
  const [drafts, setDrafts] = useState<Record<number, ProfileDraft>>({})
  const [newDraft, setNewDraft] = useState<ProfileDraft>(EMPTY_DRAFT)
  const [suggestOpen, setSuggestOpen] = useState(false)

  async function reload() {
    const data = await listPanelExpertProfiles(moduleId, true)
    setRows(data)
    setDrafts(Object.fromEntries(data.map((row) => [row.id, draftFromRow(row)])))
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listPanelExpertProfiles(moduleId, true)
      .then((data) => {
        if (cancelled) return
        setRows(data)
        setDrafts(Object.fromEntries(data.map((row) => [row.id, draftFromRow(row)])))
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

  function draftFor(row: PanelExpertProfile): ProfileDraft {
    return drafts[row.id] ?? draftFromRow(row)
  }

  async function saveRow(row: PanelExpertProfile) {
    const draft = draftFor(row)
    const sortOrder = Number(draft.sort_order)
    if (!draft.name.trim() || Number.isNaN(sortOrder)) {
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
      const updated = await updatePanelExpertProfile(row.id, {
        name: draft.name.trim(),
        description: draft.description,
        kompetensomrade: draft.kompetensomrade,
        radgivningsstil: draft.radgivningsstil,
        yrkesbakgrund: draft.yrkesbakgrund,
        professionell_anekdot: draft.professionell_anekdot,
        sort_order: sortOrder,
      })
      setRows((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setDrafts((prev) => ({ ...prev, [updated.id]: draftFromRow(updated) }))
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

  async function toggleActive(row: PanelExpertProfile, active: boolean) {
    setSavingId(row.id)
    setError(null)
    try {
      const updated = await updatePanelExpertProfile(row.id, { active })
      setRows((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  async function addRow() {
    if (!newDraft.name.trim()) {
      setError(t("tools.panelCatalog.needName"))
      return
    }
    setSavingId("new")
    setError(null)
    try {
      const created = await createPanelExpertProfile({
        module: moduleId,
        name: newDraft.name.trim(),
        description: newDraft.description,
        kompetensomrade: newDraft.kompetensomrade,
        radgivningsstil: newDraft.radgivningsstil,
        yrkesbakgrund: newDraft.yrkesbakgrund,
        professionell_anekdot: newDraft.professionell_anekdot,
      })
      setRows((prev) => [...prev, created])
      setDrafts((prev) => ({ ...prev, [created.id]: draftFromRow(created) }))
      setNewDraft(EMPTY_DRAFT)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  if (loading) return <p className="muted">{t("tools.panelCatalog.loading")}</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">{t("tools.panelCatalog.expertsTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("tools.panelCatalog.expertsIntro")}</p>
        </div>
        <AdminButton type="button" variant="secondary" size="sm" onClick={() => setSuggestOpen(true)}>
          {t("tools.panelCatalog.suggestExperts")}
        </AdminButton>
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <div className="space-y-4">
        {rows.map((row) => {
          const draft = draftFor(row)
          return (
            <div
              key={row.id}
              className="space-y-2 rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted-foreground">{row.key}</span>
                <label className="inline-flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={row.active}
                    disabled={savingId === row.id}
                    onChange={(event) => void toggleActive(row, event.target.checked)}
                  />
                  {t("tools.panelCatalog.colActive")}
                </label>
              </div>
              <label className="block text-sm">
                <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colName")}</span>
                <input
                  className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                  value={draft.name}
                  onChange={(event) =>
                    setDrafts((prev) => ({ ...prev, [row.id]: { ...draft, name: event.target.value } }))
                  }
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colDescription")}</span>
                <textarea
                  className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                  rows={2}
                  value={draft.description}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [row.id]: { ...draft, description: event.target.value },
                    }))
                  }
                />
              </label>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-sm">
                  <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colKompetens")}</span>
                  <input
                    className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                    value={draft.kompetensomrade}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [row.id]: { ...draft, kompetensomrade: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colStil")}</span>
                  <input
                    className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                    value={draft.radgivningsstil}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [row.id]: { ...draft, radgivningsstil: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colBakgrund")}</span>
                  <input
                    className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                    value={draft.yrkesbakgrund}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [row.id]: { ...draft, yrkesbakgrund: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colSort")}</span>
                  <input
                    className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                    value={draft.sort_order}
                    inputMode="numeric"
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [row.id]: { ...draft, sort_order: event.target.value },
                      }))
                    }
                  />
                </label>
              </div>
              <label className="block text-sm">
                <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colAnecdot")}</span>
                <textarea
                  className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
                  rows={2}
                  value={draft.professionell_anekdot}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [row.id]: { ...draft, professionell_anekdot: event.target.value },
                    }))
                  }
                />
              </label>
              <AdminButton
                type="button"
                variant="secondary"
                size="sm"
                disabled={savingId === row.id}
                onClick={() => void saveRow(row)}
              >
                {savingId === row.id ? t("common.saving") : t("common.save")}
              </AdminButton>
            </div>
          )
        })}
      </div>
      <form
        className="space-y-2 rounded-[var(--radius-md)] border border-dashed border-[color:var(--border-hairline)] p-3"
        onSubmit={(event) => {
          event.preventDefault()
          void addRow()
        }}
      >
        <h3 className="text-sm font-medium">{t("tools.panelCatalog.addExpert")}</h3>
        <label className="block text-sm">
          <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colName")}</span>
          <input
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
            value={newDraft.name}
            onChange={(event) => setNewDraft((prev) => ({ ...prev, name: event.target.value }))}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-muted-foreground">{t("tools.panelCatalog.colDescription")}</span>
          <textarea
            className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1"
            rows={2}
            value={newDraft.description}
            onChange={(event) => setNewDraft((prev) => ({ ...prev, description: event.target.value }))}
          />
        </label>
        <AdminButton type="submit" variant="primary" size="sm" disabled={savingId === "new"}>
          {savingId === "new" ? t("common.saving") : t("tools.panelCatalog.addExpert")}
        </AdminButton>
      </form>
      <SuggestExpertsModal
        open={suggestOpen}
        moduleId={moduleId}
        onOpenChange={setSuggestOpen}
        onAdded={() => {
          void reload().catch((err: unknown) => {
            setError(err instanceof ApiError ? err.message : t("tools.panelCatalog.loadError"))
          })
        }}
      />
    </div>
  )
}
