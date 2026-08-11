import { useCallback, useEffect, useMemo, useState } from "react"
import { AdminButton } from "@/components/ui/admin-button"
import {
  addRunAnchorPoolItems,
  fetchRunTaggableTexts,
  type RunTaggableTextRow,
} from "@/api/runs"
import { deleteAnchorPoolItem, listPoolItems } from "@/api/anchorSets"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Props = {
  runId: number
  attemptId: string
  variantId: string
}

type RowState = RunTaggableTextRow & {
  selectedTone: string | null
  selectedStyle: string | null
  addToCalibration: boolean
  busy: boolean
  error: string | null
}

function sourceRefKey(ref: Record<string, unknown>): string {
  return JSON.stringify(ref, Object.keys(ref).sort())
}

function sourceTypeLabel(
  sourceType: RunTaggableTextRow["source_type"],
  t: (key: string) => string,
): string {
  switch (sourceType) {
    case "comment":
      return t("runs.results.anchorPool.sourceComment")
    case "tick_interview":
      return t("runs.results.anchorPool.sourcePlannedInterview")
    case "posthoc_interview":
      return t("runs.results.anchorPool.sourcePosthocInterview")
    default: {
      const _exhaustive: never = sourceType
      return String(_exhaustive)
    }
  }
}

export function RunAnchorPoolPanel({ runId, attemptId, variantId }: Props) {
  const { locale, t } = useLocale()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [anchorContext, setAnchorContext] = useState<{
    tone: { id: number; name: string; labels: string[] }
    style: { id: number; name: string; labels: string[] }
  } | null>(null)
  const [rows, setRows] = useState<RowState[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchRunTaggableTexts(runId, {
        attemptId,
        variantId,
        locale,
      })
      setAnchorContext({
        tone: data.anchor_context.tone,
        style: data.anchor_context.style,
      })
      setRows(
        data.rows.map((row) => ({
          ...row,
          selectedTone: null,
          selectedStyle: null,
          addToCalibration: false,
          busy: false,
          error: null,
        })),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("runs.results.anchorPool.loadError"))
    } finally {
      setLoading(false)
    }
  }, [attemptId, locale, runId, t, variantId])

  useEffect(() => {
    void load()
  }, [load])

  const toneLabels = anchorContext?.tone.labels ?? []
  const styleLabels = anchorContext?.style.labels ?? []

  const contextLine = useMemo(() => {
    if (!anchorContext) return ""
    return t("runs.results.anchorPool.activeSets", {
      tone: anchorContext.tone.name,
      style: anchorContext.style.name,
    })
  }, [anchorContext, t])

  async function handleAdd(rowIndex: number) {
    const row = rows[rowIndex]
    if (!row || (!row.selectedTone && !row.selectedStyle)) return
    setRows((prev) =>
      prev.map((r, i) => (i === rowIndex ? { ...r, busy: true, error: null } : r)),
    )
    try {
      await addRunAnchorPoolItems(runId, {
        text: row.text,
        source_type: row.source_type,
        source_ref: row.source_ref,
        attempt_id: attemptId,
        variant_id: variantId,
        tone_label: row.selectedTone,
        style_label: row.selectedStyle,
        add_to_calibration: row.addToCalibration,
        locale,
      })
      await load()
    } catch (err) {
      setRows((prev) =>
        prev.map((r, i) =>
          i === rowIndex
            ? {
                ...r,
                busy: false,
                error: err instanceof ApiError ? err.message : t("runs.results.anchorPool.addError"),
              }
            : r,
        ),
      )
    }
  }

  async function handleRemove(
    kind: "tone" | "style",
    anchorSetId: number,
    label: string,
    rowIndex: number,
    refKey: string,
  ) {
    if (!anchorContext) return
    setRows((prev) =>
      prev.map((r, i) => (i === rowIndex ? { ...r, busy: true, error: null } : r)),
    )
    try {
      const poolItems = await listPoolItems(anchorSetId)
      const match = poolItems.find(
        (item) =>
          item.label === label &&
          JSON.stringify(item.source_ref, Object.keys(item.source_ref).sort()) === refKey,
      )
      if (!match) {
        throw new Error(t("runs.results.anchorPool.removeMissing"))
      }
      await deleteAnchorPoolItem(anchorSetId, match.id)
      await load()
    } catch (err) {
      setRows((prev) =>
        prev.map((r, i) =>
          i === rowIndex
            ? {
                ...r,
                busy: false,
                error:
                  err instanceof Error
                    ? err.message
                    : t("runs.results.anchorPool.removeError"),
              }
            : r,
        ),
      )
    }
  }

  if (loading) {
    return (
      <p className="mt-4 text-sm text-muted-foreground">
        {t("runs.results.anchorPool.loading")}
      </p>
    )
  }

  if (error) {
    return (
      <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {error}
      </p>
    )
  }

  return (
    <section className="mt-6 rounded-md border border-border bg-muted/20 px-4 py-4">
      <h3 className="text-sm font-semibold text-foreground">
        {t("runs.results.anchorPool.title")}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">{t("runs.results.anchorPool.intro")}</p>
      {contextLine ? (
        <p className="mt-2 text-xs text-db-gold-800">{contextLine}</p>
      ) : null}

      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("runs.results.anchorPool.empty")}
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-4">
          {rows.map((row, index) => {
            const refKey = sourceRefKey(row.source_ref)
            const metaAuthor =
              typeof row.meta.author === "string" ? row.meta.author : undefined
            const metaQuestion =
              typeof row.meta.question === "string" ? row.meta.question : undefined
            return (
              <li
                key={`${row.source_type}-${refKey}-${index}`}
                className="rounded border border-border bg-background px-3 py-3"
              >
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="rounded bg-muted px-2 py-0.5 font-medium">
                    {sourceTypeLabel(row.source_type, t)}
                  </span>
                  {metaAuthor ? <span>{metaAuthor}</span> : null}
                </div>
                {metaQuestion ? (
                  <p className="mb-1 text-xs text-muted-foreground">
                    {t("runs.results.anchorPool.question")}: {metaQuestion}
                  </p>
                ) : null}
                <p className="text-sm text-foreground">{row.text}</p>

                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="flex flex-col gap-1 text-xs">
                    <span className="font-medium text-muted-foreground">
                      {t("runs.results.anchorPool.toneLabel")}
                    </span>
                    <select
                      className="rounded border border-border bg-background px-2 py-1.5 text-sm"
                      value={row.selectedTone ?? ""}
                      disabled={row.busy}
                      onChange={(e) =>
                        setRows((prev) =>
                          prev.map((r, i) =>
                            i === index
                              ? { ...r, selectedTone: e.target.value || null }
                              : r,
                          ),
                        )
                      }
                    >
                      <option value="">{t("runs.results.anchorPool.none")}</option>
                      {toneLabels.map((label) => (
                        <option key={label} value={label}>
                          {label}
                        </option>
                      ))}
                    </select>
                    {row.tone_labels.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {row.tone_labels.map((label) => (
                          <button
                            key={label}
                            type="button"
                            className="rounded bg-db-gold-100 px-2 py-0.5 text-xs text-db-gold-900"
                            disabled={row.busy}
                            onClick={() =>
                              void handleRemove(
                                "tone",
                                anchorContext!.tone.id,
                                label,
                                index,
                                refKey,
                              )
                            }
                          >
                            {label} ×
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </label>

                  <label className="flex flex-col gap-1 text-xs">
                    <span className="font-medium text-muted-foreground">
                      {t("runs.results.anchorPool.styleLabel")}
                    </span>
                    <select
                      className="rounded border border-border bg-background px-2 py-1.5 text-sm"
                      value={row.selectedStyle ?? ""}
                      disabled={row.busy}
                      onChange={(e) =>
                        setRows((prev) =>
                          prev.map((r, i) =>
                            i === index
                              ? { ...r, selectedStyle: e.target.value || null }
                              : r,
                          ),
                        )
                      }
                    >
                      <option value="">{t("runs.results.anchorPool.none")}</option>
                      {styleLabels.map((label) => (
                        <option key={label} value={label}>
                          {label}
                        </option>
                      ))}
                    </select>
                    {row.style_labels.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {row.style_labels.map((label) => (
                          <button
                            key={label}
                            type="button"
                            className="rounded bg-db-gold-100 px-2 py-0.5 text-xs text-db-gold-900"
                            disabled={row.busy}
                            onClick={() =>
                              void handleRemove(
                                "style",
                                anchorContext!.style.id,
                                label,
                                index,
                                refKey,
                              )
                            }
                          >
                            {label} ×
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </label>
                </div>

                <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={row.addToCalibration}
                    disabled={row.busy}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r, i) =>
                          i === index ? { ...r, addToCalibration: e.target.checked } : r,
                        ),
                      )
                    }
                  />
                  {t("runs.results.anchorPool.addCalibration")}
                </label>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <AdminButton
                    type="button"
                    size="sm"
                    disabled={row.busy || (!row.selectedTone && !row.selectedStyle)}
                    onClick={() => void handleAdd(index)}
                  >
                    {row.busy
                      ? t("runs.results.anchorPool.adding")
                      : t("runs.results.anchorPool.add")}
                  </AdminButton>
                  {row.error ? (
                    <span className="text-xs text-destructive">{row.error}</span>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
