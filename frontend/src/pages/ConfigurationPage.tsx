import { useEffect, useMemo, useState } from "react"
import {
  listCatalog,
  SECTION_LABELS,
  SECTION_ORDER,
  updateCatalogList,
  type CatalogList,
  type CatalogSection,
} from "@/api/catalog"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { ApiError } from "@/lib/api"

type DraftMap = Record<string, string[]>

type ListEditorProps = {
  list: CatalogList
  draft: string[]
  onChange: (items: string[]) => void
  onSave: () => void
  saving: boolean
  dirty: boolean
}

function ListEditor({ list, draft, onChange, onSave, saving, dirty }: ListEditorProps) {
  function setItem(index: number, value: string) {
    onChange(draft.map((item, i) => (i === index ? value : item)))
  }

  function removeItem(index: number) {
    onChange(draft.filter((_, i) => i !== index))
  }

  function addItem() {
    onChange([...draft, ""])
  }

  function moveItem(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= draft.length) return
    const next = [...draft]
    const [row] = next.splice(index, 1)
    next.splice(target, 0, row)
    onChange(next)
  }

  return (
    <Card className="gap-0 py-4 ring-1 ring-border">
      <CardContent className="px-5">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-[color:var(--text-body)]">
              {list.title}
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              Nyckel: {list.key} · {draft.length} alternativ
            </div>
          </div>
          <AdminButton
            variant="accent"
            size="sm"
            disabled={!dirty || saving}
            onClick={onSave}
          >
            {saving ? "Sparar…" : "Spara"}
          </AdminButton>
        </div>

        <ul className="flex flex-col gap-2">
          {draft.map((item, index) => (
            <li key={`${list.key}-${index}`} className="flex items-center gap-2">
              <input
                className="dsearch flex-1"
                value={item}
                placeholder="Alternativ…"
                onChange={(e) => setItem(index, e.target.value)}
              />
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                disabled={index === 0}
                onClick={() => moveItem(index, -1)}
                aria-label="Flytta upp"
              >
                ↑
              </button>
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                disabled={index === draft.length - 1}
                onClick={() => moveItem(index, 1)}
                aria-label="Flytta ner"
              >
                ↓
              </button>
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-destructive hover:bg-destructive/5"
                onClick={() => removeItem(index)}
              >
                Ta bort
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-3">
          <AdminButton variant="secondary" size="sm" onClick={addItem}>
            + Lägg till
          </AdminButton>
        </div>
      </CardContent>
    </Card>
  )
}

function sameItems(a: string[], b: string[]) {
  if (a.length !== b.length) return false
  return a.every((v, i) => v === b[i])
}

export function ConfigurationPage() {
  const [lists, setLists] = useState<CatalogList[]>([])
  const [drafts, setDrafts] = useState<DraftMap>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listCatalog()
      .then((data) => {
        if (cancelled) return
        setLists(data)
        const next: DraftMap = {}
        for (const list of data) {
          next[list.key] = [...list.items]
        }
        setDrafts(next)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Kunde inte hämta grunddata",
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(t)
  }, [toast])

  const bySection = useMemo(() => {
    const map = new Map<CatalogSection, CatalogList[]>()
    for (const section of SECTION_ORDER) {
      map.set(section, [])
    }
    for (const list of lists) {
      const bucket = map.get(list.section) ?? []
      bucket.push(list)
      map.set(list.section, bucket)
    }
    return map
  }, [lists])

  function setDraft(key: string, items: string[]) {
    setDrafts((prev) => ({ ...prev, [key]: items }))
  }

  async function saveList(key: string) {
    const draft = drafts[key] ?? []
    setSavingKey(key)
    try {
      const updated = await updateCatalogList(key, draft)
      setLists((prev) => prev.map((list) => (list.key === key ? updated : list)))
      setDrafts((prev) => ({ ...prev, [key]: [...updated.items] }))
      setToast(`${updated.title} sparades`)
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : "Kunde inte spara")
    } finally {
      setSavingKey(null)
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>Konfiguration</h1>
            <p className="muted">
              Grunddata för dropdowns i persona-kompositören. Ändringar syns nästa
              gång formuläret laddas. Befintliga personas behåller sina värden.
            </p>
          </div>
        </div>

        {loading && <p className="muted">Hämtar grunddata…</p>}
        {error && <p className="text-destructive">{error}</p>}

        {!loading && !error && (
          <div className="flex flex-col gap-10">
            {SECTION_ORDER.map((section) => {
              const sectionLists = bySection.get(section) ?? []
              if (sectionLists.length === 0) return null
              return (
                <section key={section}>
                  <h2 className="mb-4 text-base font-medium text-[color:var(--text-body)]">
                    {SECTION_LABELS[section]}
                  </h2>
                  <div className="grid gap-4 lg:grid-cols-2">
                    {sectionLists.map((list) => {
                      const draft = drafts[list.key] ?? list.items
                      const dirty = !sameItems(draft, list.items)
                      return (
                        <ListEditor
                          key={list.key}
                          list={list}
                          draft={draft}
                          dirty={dirty}
                          saving={savingKey === list.key}
                          onChange={(items) => setDraft(list.key, items)}
                          onSave={() => void saveList(list.key)}
                        />
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </div>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
