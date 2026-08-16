import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deleteAnchorSet,
  duplicateAnchorSet,
  listAnchorSets,
  publishAnchorSet,
  type AnchorKind,
  type AnchorLocale,
  type AnchorPublishGateDetail,
  type AnchorValidationStatus,
  type SsrAnchorSet,
} from "@/api/anchorSets"
import {
  getLabelVocabulary,
  patchLabelVocabulary,
  type LabelVocabulary,
  type LabelVocabularyEntry,
} from "@/api/labelVocabularies"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = ReturnType<typeof useLocale>["t"]

function kindLabel(kind: AnchorKind, t: Translate): string {
  return kind === "tone" ? t("anchorSets.kindTone") : t("anchorSets.kindStyle")
}

function statusLabel(status: SsrAnchorSet["status"], t: Translate): string {
  return status === "published"
    ? t("anchorSets.statusPublished")
    : t("anchorSets.statusDraft")
}

function validationLabel(status: AnchorValidationStatus, t: Translate): string {
  switch (status) {
    case "ok":
      return t("anchorSets.validation.ok")
    case "stale":
      return t("anchorSets.validation.stale")
    case "low":
      return t("anchorSets.validation.low")
    case "untested":
      return t("anchorSets.validation.untested")
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function isPublishGateDetail(body: unknown): body is AnchorPublishGateDetail {
  return (
    typeof body === "object" &&
    body !== null &&
    "code" in body &&
    "requires_acknowledgement" in body
  )
}

type AnchorItemProps = {
  row: SsrAnchorSet
  t: Translate
  onPublish: (id: number) => void
  onDuplicate: (id: number) => void
  onDelete: (id: number) => void
}

function AnchorActions({ row, t, onPublish, onDuplicate, onDelete }: AnchorItemProps) {
  return (
    <>
      <Link className="primary text-sm" to={`/tools/anchor-sets/${row.id}/edit`}>
        {t("anchorSets.list.edit")}
      </Link>
      {row.status === "draft" ? (
        <AdminButton
          type="button"
          variant="secondary"
          onClick={() => void onPublish(row.id)}
        >
          {t("anchorSets.list.publish")}
        </AdminButton>
      ) : (
        <AdminButton
          type="button"
          variant="secondary"
          onClick={() => void onDuplicate(row.id)}
        >
          {t("anchorSets.list.duplicate")}
        </AdminButton>
      )}
      {row.status === "draft" ? (
        <AdminButton
          type="button"
          variant="secondary"
          onClick={() => void onDelete(row.id)}
        >
          {t("common.delete")}
        </AdminButton>
      ) : null}
    </>
  )
}

function AnchorCard(props: AnchorItemProps) {
  const { row, t } = props
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4 space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="font-medium">{row.name}</div>
              <div className="text-xs text-muted-foreground">
                {kindLabel(row.kind, t)} · {row.locale.toUpperCase()} · v
                {row.version}
              </div>
            </div>
            <span className="rounded-full border px-2 py-0.5 text-[11px]">
              {statusLabel(row.status, t)}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{t("anchorSets.list.labelCount", { count: row.labels.length })}</span>
            <span>·</span>
            <span>
              {t("anchorSets.list.calibrationCount", { count: row.calibration_item_count })}
            </span>
            {row.calibration_accuracy != null ? (
              <>
                <span>·</span>
                <span>
                  {t("anchorSets.list.macroAccuracy", {
                    pct: Math.round(row.calibration_accuracy * 1000) / 10,
                  })}
                </span>
              </>
            ) : null}
            <span className="rounded-full border px-2 py-0.5 text-[10px]">
              {validationLabel(row.validation_status, t)}
            </span>
          </div>
          <div className="flex flex-wrap gap-2 pt-2">
            <AnchorActions {...props} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function AnchorListRow(props: AnchorItemProps) {
  const { row, t } = props
  const metaParts = [
    t("anchorSets.list.labelCount", { count: row.labels.length }),
    t("anchorSets.list.calibrationCount", { count: row.calibration_item_count }),
  ]
  if (row.calibration_accuracy != null) {
    metaParts.push(
      t("anchorSets.list.macroAccuracy", {
        pct: Math.round(row.calibration_accuracy * 1000) / 10,
      }),
    )
  }
  return (
    <div className="admin-list-row admin-list-anchors">
      <div>
        <div className="nm">{row.name}</div>
        <div className="meta">
          {kindLabel(row.kind, t)} · {row.locale.toUpperCase()} · v{row.version}
        </div>
      </div>
      <span className="rounded-full border px-2 py-0.5 text-[11px]">
        {statusLabel(row.status, t)}
      </span>
      <span className="rounded-full border px-2 py-0.5 text-[10px]">
        {validationLabel(row.validation_status, t)}
      </span>
      <div className="cell">{metaParts.join(" · ")}</div>
      <div className="admin-list-actions">
        <AnchorActions {...props} />
      </div>
    </div>
  )
}

type VocabColumnProps = {
  kind: AnchorKind
  locale: AnchorLocale
  vocab: LabelVocabulary | null
  t: Translate
  onUpdated: (next: LabelVocabulary) => void
  onError: (message: string) => void
  onToast: (message: string) => void
}

function VocabColumn({
  kind,
  locale,
  vocab,
  t,
  onUpdated,
  onError,
  onToast,
}: VocabColumnProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [newLabel, setNewLabel] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setDrafts({})
    setNewLabel("")
  }, [vocab?.updated_at, kind, locale])

  const title =
    kind === "tone" ? t("anchorSets.vocab.toneTitle") : t("anchorSets.vocab.styleTitle")
  const entries = vocab?.entries ?? []

  function displayLabel(entry: LabelVocabularyEntry): string {
    return drafts[entry.key] ?? entry.label
  }

  async function commitRename(entry: LabelVocabularyEntry) {
    const next = (drafts[entry.key] ?? entry.label).trim()
    if (!next || next === entry.label) {
      setDrafts((prev) => {
        const copy = { ...prev }
        delete copy[entry.key]
        return copy
      })
      return
    }
    setBusy(true)
    try {
      const updated = await patchLabelVocabulary(kind, locale, {
        rename: [{ key: entry.key, new_label: next }],
      })
      onUpdated(updated)
      onToast(t("anchorSets.vocab.renamed"))
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.message : t("anchorSets.vocab.saveError"))
      setDrafts((prev) => {
        const copy = { ...prev }
        delete copy[entry.key]
        return copy
      })
    } finally {
      setBusy(false)
    }
  }

  async function onAdd() {
    const label = newLabel.trim()
    if (!label) return
    setBusy(true)
    try {
      const updated = await patchLabelVocabulary(kind, locale, { add: [{ label }] })
      setNewLabel("")
      onUpdated(updated)
      onToast(t("anchorSets.vocab.added"))
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.message : t("anchorSets.vocab.saveError"))
    } finally {
      setBusy(false)
    }
  }

  async function onRemove(entry: LabelVocabularyEntry) {
    setBusy(true)
    try {
      const updated = await patchLabelVocabulary(kind, locale, {
        remove: [{ key: entry.key }],
      })
      onUpdated(updated)
      onToast(t("anchorSets.vocab.removed"))
    } catch (err: unknown) {
      onError(err instanceof ApiError ? err.message : t("anchorSets.vocab.saveError"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="mb-0.5 text-sm font-semibold">{title}</div>
      <p className="mb-2.5 mt-0 text-[11px] text-muted-foreground">
        {t("anchorSets.vocab.sharedHint", { kind: kindLabel(kind, t) })}
      </p>
      <div className="mb-2.5 flex flex-col gap-2">
        {entries.map((entry) => {
          const usage = vocab?.usage[entry.key] ?? 0
          const canRemove = usage === 0 && entries.length > 1
          return (
            <div key={entry.key} className="flex items-center gap-2">
              <input
                className="dsearch min-w-0 flex-1"
                value={displayLabel(entry)}
                disabled={busy}
                onChange={(e) =>
                  setDrafts((prev) => ({ ...prev, [entry.key]: e.target.value }))
                }
                onBlur={() => void commitRename(entry)}
              />
              <span className="whitespace-nowrap text-[10.5px] text-muted-foreground">
                {t("anchorSets.vocab.usageCount", { count: usage })}
              </span>
              <AdminButton
                type="button"
                variant="secondary"
                size="sm"
                disabled={!canRemove || busy}
                title={
                  canRemove
                    ? t("anchorSets.vocab.remove")
                    : t("anchorSets.vocab.removeDisabledTitle", { count: usage })
                }
                onClick={() => void onRemove(entry)}
              >
                {t("anchorSets.vocab.remove")}
              </AdminButton>
            </div>
          )
        })}
      </div>
      <div className="flex gap-2">
        <input
          className="dsearch min-w-0 flex-1"
          value={newLabel}
          disabled={busy}
          placeholder={t("anchorSets.vocab.newPlaceholder")}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              void onAdd()
            }
          }}
        />
        <AdminButton
          type="button"
          variant="primary"
          disabled={busy || !newLabel.trim()}
          onClick={() => void onAdd()}
        >
          {t("anchorSets.vocab.add")}
        </AdminButton>
      </div>
    </div>
  )
}

type LabelVocabPanelProps = {
  localeFilter: "" | AnchorLocale
  t: Translate
  onToast: (message: string) => void
}

function LabelVocabPanel({ localeFilter, t, onToast }: LabelVocabPanelProps) {
  const [panelLocale, setPanelLocale] = useState<AnchorLocale>(
    localeFilter || "sv",
  )
  const [tone, setTone] = useState<LabelVocabulary | null>(null)
  const [style, setStyle] = useState<LabelVocabulary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (localeFilter) setPanelLocale(localeFilter)
  }, [localeFilter])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      getLabelVocabulary("tone", panelLocale),
      getLabelVocabulary("style", panelLocale),
    ])
      .then(([toneVocab, styleVocab]) => {
        if (cancelled) return
        setTone(toneVocab)
        setStyle(styleVocab)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.vocab.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [panelLocale, t])

  return (
    <div className="mb-6 rounded-[var(--radius-lg)] border border-[color:var(--border-hairline)] p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">{t("anchorSets.vocab.title")}</div>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            {t("anchorSets.vocab.intro")}
          </p>
        </div>
        {!localeFilter ? (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{t("anchorSets.vocab.localeLabel")}</span>
            <select
              className="dsel"
              value={panelLocale}
              onChange={(e) => setPanelLocale(e.target.value as AnchorLocale)}
            >
              <option value="sv">{t("configurations.language.sv")}</option>
              <option value="en">{t("configurations.language.en")}</option>
            </select>
          </label>
        ) : null}
      </div>
      {loading ? <p className="muted text-sm">{t("anchorSets.list.loading")}</p> : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      {!loading ? (
        <div className="grid gap-6 md:grid-cols-2">
          <VocabColumn
            kind="tone"
            locale={panelLocale}
            vocab={tone}
            t={t}
            onUpdated={setTone}
            onError={setError}
            onToast={onToast}
          />
          <VocabColumn
            kind="style"
            locale={panelLocale}
            vocab={style}
            t={t}
            onUpdated={setStyle}
            onError={setError}
            onToast={onToast}
          />
        </div>
      ) : null}
    </div>
  )
}

export function AnchorSetsPage() {
  const { t } = useLocale()
  const [rows, setRows] = useState<SsrAnchorSet[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [kindFilter, setKindFilter] = useState<"" | AnchorKind>("")
  const [localeFilter, setLocaleFilter] = useState<"" | AnchorLocale>("")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)
  const [showVocab, setShowVocab] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listAnchorSets()
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("anchorSets.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const filtered = useMemo(() => {
    return rows.filter((row) => {
      if (kindFilter && row.kind !== kindFilter) return false
      if (localeFilter && row.locale !== localeFilter) return false
      return true
    })
  }, [rows, kindFilter, localeFilter])

  async function onPublish(id: number) {
    try {
      const updated = await publishAnchorSet(id)
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)))
      setToast(t("anchorSets.list.published"))
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409 && isPublishGateDetail(err.body)) {
        const gate = err.body
        const pct =
          gate.accuracy != null ? Math.round(gate.accuracy * 1000) / 10 : null
        const confirmed = window.confirm(
          t("anchorSets.list.publishConfirm", {
            detail: gate.detail,
            pct: pct != null ? String(pct) : "—",
            missing: gate.missing_labels.join(", ") || "—",
          }),
        )
        if (!confirmed) return
        try {
          const updated = await publishAnchorSet(id, { acknowledge_warnings: true })
          setRows((prev) => prev.map((r) => (r.id === id ? updated : r)))
          setToast(t("anchorSets.list.publishedWithOverride"))
          return
        } catch (retryErr: unknown) {
          setError(retryErr instanceof ApiError ? retryErr.message : t("common.saveError"))
          return
        }
      }
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function onDuplicate(id: number) {
    try {
      const copy = await duplicateAnchorSet(id)
      setRows((prev) => [copy, ...prev])
      setToast(t("anchorSets.list.duplicated"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  async function onDelete(id: number) {
    try {
      await deleteAnchorSet(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
      setToast(t("anchorSets.list.deleted"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    }
  }

  return (
    <div>
      <div className="head-row">
        <div>
          <h1>{t("anchorSets.list.title")}</h1>
          <p className="muted">{t("anchorSets.list.intro")}</p>
        </div>
      </div>

      <div className="controls-row">
        <div className="controls-left">
          <select
            className="dsel"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value as "" | AnchorKind)}
          >
            <option value="">{t("anchorSets.list.allKinds")}</option>
            <option value="tone">{t("anchorSets.kindTone")}</option>
            <option value="style">{t("anchorSets.kindStyle")}</option>
          </select>
          <select
            className="dsel"
            value={localeFilter}
            onChange={(e) => setLocaleFilter(e.target.value as "" | AnchorLocale)}
          >
            <option value="">{t("anchorSets.list.allLocales")}</option>
            <option value="sv">{t("configurations.language.sv")}</option>
            <option value="en">{t("configurations.language.en")}</option>
          </select>
        </div>
        <div className="controls-right">
          <ViewToggle value={view} onChange={setView} />
          <AdminButton
            type="button"
            variant="secondary"
            onClick={() => setShowVocab((open) => !open)}
          >
            {showVocab ? t("anchorSets.vocab.toggleHide") : t("anchorSets.vocab.toggleShow")}
          </AdminButton>
          <Link
            to="/tools/anchor-sets/new"
            className="admin-cta inline-flex h-9 shrink-0 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          >
            {t("anchorSets.list.new")}
          </Link>
        </div>
      </div>

      {showVocab ? (
        <LabelVocabPanel
          localeFilter={localeFilter}
          t={t}
          onToast={setToast}
        />
      ) : null}

      {loading && <p className="muted">{t("anchorSets.list.loading")}</p>}
      {error && <p className="text-destructive">{error}</p>}
      {toast && <p className="text-sm text-[color:var(--db-success)]">{toast}</p>}

      {!loading && filtered.length === 0 ? (
        <p className="muted">{t("anchorSets.list.empty")}</p>
      ) : view === "grid" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((row) => (
            <AnchorCard
              key={row.id}
              row={row}
              t={t}
              onPublish={onPublish}
              onDuplicate={onDuplicate}
              onDelete={onDelete}
            />
          ))}
        </div>
      ) : (
        <div className="admin-list-stack">
          {filtered.map((row) => (
            <AnchorListRow
              key={row.id}
              row={row}
              t={t}
              onPublish={onPublish}
              onDuplicate={onDuplicate}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}
