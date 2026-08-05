import { useEffect, useMemo, useState } from "react"
import {
  blankCatalogItem,
  listCatalog,
  SECTION_ORDER,
  updateCatalogList,
  type CatalogItem,
  type CatalogList,
  type CatalogSection,
} from "@/api/catalog"
import { DistrictMapModal } from "@/components/config/DistrictMapModal"
import { DistrictMapPreview } from "@/components/config/DistrictMapPreview"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function sectionLabel(section: CatalogSection, t: Translate): string {
  switch (section) {
    case "demografi":
      return t("config.page.sectionDemography")
    case "politik":
      return t("config.page.sectionPolitics")
    case "varderingar":
      return t("config.page.sectionValues")
    case "rost_media":
      return t("config.page.sectionVoiceMedia")
    case "simulering":
      return t("config.page.sectionSimulation")
    default: {
      const exhaustive: never = section
      return exhaustive
    }
  }
}

type DraftMap = Record<string, CatalogItem[]>

type ListEditorProps = {
  list: CatalogList
  draft: CatalogItem[]
  onChange: (items: CatalogItem[]) => void
  onSave: () => void
  saving: boolean
  dirty: boolean
}

function sameItems(a: CatalogItem[], b: CatalogItem[]) {
  if (a.length !== b.length) return false
  return a.every((item, i) => {
    const other = b[i]
    if (item.label !== other.label) return false
    if (item.description !== other.description) return false
    if (item.bounds === null && other.bounds === null) return true
    if (!item.bounds || !other.bounds) return false
    return (
      item.bounds.south === other.bounds.south &&
      item.bounds.west === other.bounds.west &&
      item.bounds.north === other.bounds.north &&
      item.bounds.east === other.bounds.east
    )
  })
}

function LabelListEditor({
  list,
  draft,
  onChange,
  onSave,
  saving,
  dirty,
}: ListEditorProps) {
  const { t } = useLocale()

  function setLabel(index: number, value: string) {
    onChange(
      draft.map((item, i) =>
        i === index ? { ...item, label: value } : item,
      ),
    )
  }

  function removeItem(index: number) {
    onChange(draft.filter((_, i) => i !== index))
  }

  function addItem() {
    onChange([...draft, blankCatalogItem()])
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
              {t("config.page.keyLabel", { key: list.key, count: draft.length })}
            </div>
          </div>
          <AdminButton
            variant="accent"
            size="sm"
            disabled={!dirty || saving}
            onClick={onSave}
          >
            {saving ? t("common.saving") : t("common.save")}
          </AdminButton>
        </div>

        <ul className="flex flex-col gap-2">
          {draft.map((item, index) => (
            <li key={`${list.key}-${index}`} className="flex items-center gap-2">
              <input
                className="dsearch min-w-0 flex-1"
                value={item.label}
                placeholder={t("config.page.optionPlaceholder")}
                onChange={(e) => setLabel(index, e.target.value)}
              />
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                disabled={index === 0}
                onClick={() => moveItem(index, -1)}
                aria-label={t("config.page.moveUp")}
              >
                ↑
              </button>
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                disabled={index === draft.length - 1}
                onClick={() => moveItem(index, 1)}
                aria-label={t("config.page.moveDown")}
              >
                ↓
              </button>
              <button
                type="button"
                className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-destructive hover:bg-destructive/5"
                onClick={() => removeItem(index)}
              >
                {t("common.delete")}
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-3">
          <AdminButton variant="secondary" size="sm" onClick={addItem}>
            {t("config.page.addOption")}
          </AdminButton>
        </div>
      </CardContent>
    </Card>
  )
}

function DistrictListEditor({
  list,
  draft,
  onChange,
  onSave,
  saving,
  dirty,
}: ListEditorProps) {
  const { t } = useLocale()
  const [mapIndex, setMapIndex] = useState<number | null>(null)

  function patchItem(index: number, patch: Partial<CatalogItem>) {
    onChange(draft.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  }

  function removeItem(index: number) {
    onChange(draft.filter((_, i) => i !== index))
    if (mapIndex === index) setMapIndex(null)
    else if (mapIndex !== null && mapIndex > index) setMapIndex(mapIndex - 1)
  }

  function addItem() {
    onChange([...draft, blankCatalogItem(t("config.page.newDistrict"))])
  }

  function moveItem(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= draft.length) return
    const next = [...draft]
    const [row] = next.splice(index, 1)
    next.splice(target, 0, row)
    onChange(next)
    if (mapIndex === index) setMapIndex(target)
    else if (mapIndex === target) setMapIndex(index)
  }

  const mapDistrict = mapIndex !== null ? draft[mapIndex] : null

  return (
    <Card className="gap-0 py-4 ring-1 ring-border">
      <CardContent className="px-5">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-[color:var(--text-body)]">
              {list.title}
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {t("config.page.districtHint", { count: draft.length })}
            </div>
          </div>
          <AdminButton
            variant="accent"
            size="sm"
            disabled={!dirty || saving}
            onClick={onSave}
          >
            {saving ? t("common.saving") : t("common.save")}
          </AdminButton>
        </div>

        <ul className="flex flex-col gap-3">
          {draft.map((item, index) => (
            <li
              key={`ort-${index}`}
              className="grid gap-3 rounded border border-[color:var(--border-hairline)] p-3 sm:grid-cols-[minmax(0,1fr)_220px]"
            >
              <div className="min-w-0">
                <input
                  className="dsearch mb-2 !w-full"
                  value={item.label}
                  placeholder={t("config.page.districtNamePlaceholder")}
                  onChange={(e) => patchItem(index, { label: e.target.value })}
                />
                <textarea
                  className="dsearch min-h-[88px] !w-full resize-y"
                  value={item.description}
                  placeholder={t("config.page.districtDescPlaceholder")}
                  onChange={(e) =>
                    patchItem(index, { description: e.target.value })
                  }
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <AdminButton
                    variant="secondary"
                    size="sm"
                    onClick={() => setMapIndex(index)}
                  >
                    {item.bounds ? t("config.page.editMap") : t("config.page.setMapArea")}
                  </AdminButton>
                  <span className="flex-1" />
                  <button
                    type="button"
                    className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                    disabled={index === 0}
                    onClick={() => moveItem(index, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                    disabled={index === draft.length - 1}
                    onClick={() => moveItem(index, 1)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-destructive hover:bg-destructive/5"
                    onClick={() => removeItem(index)}
                  >
                    {t("common.delete")}
                  </button>
                </div>
              </div>
              <DistrictMapPreview
                bounds={item.bounds}
                label={item.label}
                onOpen={() => setMapIndex(index)}
              />
            </li>
          ))}
        </ul>

        <div className="mt-3">
          <AdminButton variant="secondary" size="sm" onClick={addItem}>
            {t("config.page.addDistrict")}
          </AdminButton>
        </div>

        {mapDistrict && mapIndex !== null && (
          <DistrictMapModal
            open
            district={mapDistrict}
            others={draft.filter((_, i) => i !== mapIndex)}
            onClose={() => setMapIndex(null)}
            onChangeBounds={(bounds) => patchItem(mapIndex, { bounds })}
          />
        )}
      </CardContent>
    </Card>
  )
}

export function ConfigurationPage() {
  const { t } = useLocale()
  const [lists, setLists] = useState<CatalogList[]>([])
  const [drafts, setDrafts] = useState<DraftMap>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<CatalogSection>(
    SECTION_ORDER[0],
  )
  const [activeListKey, setActiveListKey] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listCatalog()
      .then((data) => {
        if (cancelled) return
        setLists(data)
        const next: DraftMap = {}
        for (const list of data) {
          next[list.key] = list.items.map((item) => ({ ...item }))
        }
        setDrafts(next)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t("config.page.loadError"),
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const visibleSections = useMemo(
    () =>
      SECTION_ORDER.filter(
        (section) => (bySection.get(section) ?? []).length > 0,
      ),
    [bySection],
  )

  const sectionLists = useMemo(
    () => bySection.get(activeSection) ?? [],
    [bySection, activeSection],
  )

  useEffect(() => {
    if (visibleSections.length === 0) return
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0])
    }
  }, [visibleSections, activeSection])

  useEffect(() => {
    if (sectionLists.length === 0) {
      setActiveListKey(null)
      return
    }
    if (!activeListKey || !sectionLists.some((list) => list.key === activeListKey)) {
      setActiveListKey(sectionLists[0].key)
    }
  }, [sectionLists, activeListKey])

  function setDraft(key: string, items: CatalogItem[]) {
    setDrafts((prev) => ({ ...prev, [key]: items }))
  }

  async function saveList(key: string) {
    const draft = drafts[key] ?? []
    setSavingKey(key)
    try {
      const updated = await updateCatalogList(key, draft)
      setLists((prev) => prev.map((list) => (list.key === key ? updated : list)))
      setDrafts((prev) => ({
        ...prev,
        [key]: updated.items.map((item) => ({ ...item })),
      }))
      setToast(t("config.page.savedToast", { title: updated.title }))
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingKey(null)
    }
  }

  const activeList =
    sectionLists.find((list) => list.key === activeListKey) ?? sectionLists[0] ?? null
  const activeDraft = activeList
    ? (drafts[activeList.key] ?? activeList.items)
    : null
  const activeDirty =
    activeList && activeDraft
      ? !sameItems(activeDraft, activeList.items)
      : false

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("config.page.title")}</h1>
            <p className="muted">{t("config.page.intro")}</p>
          </div>
        </div>

        {loading && <p className="muted">{t("config.page.loading")}</p>}
        {error && <p className="text-destructive">{error}</p>}

        {!loading && !error && (
          <div>
            <div
              role="tablist"
              aria-label={t("config.page.tablistAria")}
              className="mb-3 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
            >
              {visibleSections.map((section) => {
                const selected = section === activeSection
                return (
                  <button
                    key={section}
                    type="button"
                    role="tab"
                    id={`config-tab-${section}`}
                    aria-selected={selected}
                    aria-controls={`config-panel-${section}`}
                    tabIndex={selected ? 0 : -1}
                    className={
                      selected
                        ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                        : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                    }
                    onClick={() => {
                      setActiveSection(section)
                      const first = bySection.get(section)?.[0]
                      setActiveListKey(first?.key ?? null)
                    }}
                  >
                    {sectionLabel(section, t)}
                  </button>
                )
              })}
            </div>

            <div
              role="tabpanel"
              id={`config-panel-${activeSection}`}
              aria-labelledby={`config-tab-${activeSection}`}
            >
              {sectionLists.length > 0 && (
                <div
                  role="tablist"
                  aria-label={t("config.page.listTablistAria", { section: sectionLabel(activeSection, t) })}
                  className="mb-5 flex flex-wrap gap-2"
                >
                  {sectionLists.map((list) => {
                    const selected = list.key === activeList?.key
                    const dirty = !sameItems(
                      drafts[list.key] ?? list.items,
                      list.items,
                    )
                    return (
                      <button
                        key={list.key}
                        type="button"
                        role="tab"
                        id={`config-list-tab-${list.key}`}
                        aria-selected={selected}
                        aria-controls={`config-list-panel-${list.key}`}
                        tabIndex={selected ? 0 : -1}
                        className={
                          selected
                            ? "inline-flex items-center gap-1.5 rounded-md bg-db-ink-950 px-3 py-1.5 text-sm text-db-ink-0"
                            : "inline-flex items-center gap-1.5 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-1.5 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                        }
                        onClick={() => setActiveListKey(list.key)}
                      >
                        {list.title}
                        {dirty && (
                          <span
                            className={
                              selected
                                ? "h-1.5 w-1.5 rounded-full bg-db-gold-500"
                                : "h-1.5 w-1.5 rounded-full bg-db-ink-950"
                            }
                            title={t("config.page.unsavedChanges")}
                            aria-label={t("config.page.unsavedChanges")}
                          />
                        )}
                      </button>
                    )
                  })}
                </div>
              )}

              {activeList && activeDraft && (
                <div
                  role="tabpanel"
                  id={`config-list-panel-${activeList.key}`}
                  aria-labelledby={`config-list-tab-${activeList.key}`}
                >
                  {activeList.key === "ort" ? (
                    <DistrictListEditor
                      list={activeList}
                      draft={activeDraft}
                      dirty={activeDirty}
                      saving={savingKey === activeList.key}
                      onChange={(items) => setDraft(activeList.key, items)}
                      onSave={() => void saveList(activeList.key)}
                    />
                  ) : (
                    <LabelListEditor
                      list={activeList}
                      draft={activeDraft}
                      dirty={activeDirty}
                      saving={savingKey === activeList.key}
                      onChange={(items) => setDraft(activeList.key, items)}
                      onSave={() => void saveList(activeList.key)}
                    />
                  )}
                </div>
              )}
            </div>
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
