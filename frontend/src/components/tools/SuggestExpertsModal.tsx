import { useEffect, useRef, useState } from "react"
import { createPanelExpertProfile, suggestPanelExperts, type ExpertCandidate } from "@/api/panelCatalog"
import { listUnderlag, type UnderlagExtractionStatus, type UnderlagFile } from "@/api/underlag"
import { AdminButton } from "@/components/ui/admin-button"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type Step = "pick" | "loading" | "review"

function statusKey(status: UnderlagExtractionStatus | null): MessageKey {
  switch (status) {
    case "ok":
      return "underlag.status.ok"
    case "failed":
      return "underlag.status.failed"
    case "empty":
      return "underlag.status.empty"
    case "unsupported":
      return "underlag.status.unsupported"
    case null:
      return "underlag.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function statusVariant(
  status: UnderlagExtractionStatus | null,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "ok":
      return "default"
    case "failed":
    case "unsupported":
      return "destructive"
    case "empty":
      return "outline"
    case null:
      return "secondary"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

export function SuggestExpertsModal({
  open,
  moduleId,
  onOpenChange,
  onAdded,
}: {
  open: boolean
  moduleId: string
  onOpenChange: (open: boolean) => void
  onAdded: () => void
}) {
  const { t, intl, locale } = useLocale()
  const dateFmt = new Intl.DateTimeFormat(intl, { dateStyle: "medium" })
  const [step, setStep] = useState<Step>("pick")
  const [rows, setRows] = useState<UnderlagFile[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<ExpertCandidate[]>([])
  const [checked, setChecked] = useState<boolean[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestGen = useRef(0)

  useEffect(() => {
    if (!open) {
      requestGen.current += 1
      setStep("pick")
      setRows([])
      setSelectedId(null)
      setCandidates([])
      setChecked([])
      setSaving(false)
      setError(null)
      return
    }
    let cancelled = false
    setLoadingList(true)
    setError(null)
    listUnderlag(moduleId)
      .then((listed) => {
        if (!cancelled) setRows(listed)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("underlag.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false)
      })
    return () => {
      cancelled = true
    }
  }, [moduleId, open, t])

  async function generate() {
    if (selectedId == null) {
      setError(t("tools.panelCatalog.suggestNeedUnderlag"))
      return
    }
    const token = ++requestGen.current
    setStep("loading")
    setError(null)
    try {
      const suggested = await suggestPanelExperts({
        underlag_id: selectedId,
        module: moduleId,
        language: locale,
      })
      if (token !== requestGen.current) return
      setCandidates(suggested)
      setChecked(suggested.map(() => true))
      setStep("review")
    } catch (err: unknown) {
      if (token !== requestGen.current) return
      setError(err instanceof ApiError ? err.message : t("tools.panelCatalog.suggestError"))
      setStep("pick")
    }
  }

  async function addSelected() {
    const chosen = candidates.filter((_, index) => checked[index])
    if (chosen.length === 0) {
      setError(t("tools.panelCatalog.suggestNeedCandidate"))
      return
    }
    setSaving(true)
    setError(null)
    const saved = new Set<number>()
    try {
      for (const [index, candidate] of candidates.entries()) {
        if (!checked[index]) continue
        await createPanelExpertProfile({
          module: moduleId,
          name: candidate.name,
          description: candidate.description,
          kompetensomrade: candidate.kompetensomrade,
          radgivningsstil: candidate.radgivningsstil,
          yrkesbakgrund: candidate.yrkesbakgrund,
          professionell_anekdot: candidate.professionell_anekdot,
        })
        saved.add(index)
      }
      onAdded()
      onOpenChange(false)
    } catch (err: unknown) {
      const leftover = candidates
        .map((candidate, index) => ({
          candidate,
          checked: checked[index] ?? false,
          saved: saved.has(index),
        }))
        .filter((row) => !row.saved)
      setCandidates(leftover.map((row) => row.candidate))
      setChecked(leftover.map((row) => row.checked))
      onAdded()
      setError(err instanceof ApiError ? err.message : t("tools.panelCatalog.suggestSaveError"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="theme-admin max-h-[min(880px,92vh)] w-full max-w-2xl overflow-hidden bg-db-ink-0 p-0 sm:max-w-2xl"
        showCloseButton={false}
      >
        <div className="flex max-h-[min(880px,92vh)] flex-col">
          <DialogHeader className="border-b border-[color:var(--border-hairline)] px-5 py-4">
            <DialogTitle>{t("tools.panelCatalog.suggestTitle")}</DialogTitle>
            <DialogDescription>{t("tools.panelCatalog.suggestIntro")}</DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {error ? (
              <p className="mb-3 text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}

            {step === "pick" || step === "loading" ? (
              <div className="min-h-0 overflow-y-auto rounded-md border border-[color:var(--border-hairline)]">
                {loadingList ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : rows.length === 0 ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">
                    {t("tools.panelCatalog.suggestEmptyUnderlag")}
                  </p>
                ) : (
                  <ul className="divide-y divide-[color:var(--border-hairline)]">
                    {rows.map((row) => {
                      const usable = row.extraction_status === "ok"
                      const selected = selectedId === row.id
                      return (
                        <li key={row.id}>
                          <button
                            type="button"
                            disabled={!usable || step === "loading"}
                            className={`flex w-full flex-col items-start gap-1 px-3 py-2.5 text-left hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50 ${
                              selected ? "bg-muted" : ""
                            }`}
                            onClick={() => setSelectedId(row.id)}
                          >
                            <span className="text-sm font-medium">{row.filename}</span>
                            <span className="flex flex-wrap items-center gap-2">
                              <Badge variant={statusVariant(row.extraction_status)}>
                                {t(statusKey(row.extraction_status))}
                              </Badge>
                              {row.created_at ? (
                                <span className="text-xs text-muted-foreground">
                                  {dateFmt.format(new Date(row.created_at))}
                                </span>
                              ) : null}
                              {!usable ? (
                                <span className="text-xs text-muted-foreground">
                                  {t("tools.panelCatalog.suggestUnavailable")}
                                </span>
                              ) : null}
                            </span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            ) : null}

            {step === "loading" ? (
              <p className="mt-3 text-sm text-muted-foreground">{t("tools.panelCatalog.suggestGenerating")}</p>
            ) : null}

            {step === "review" ? (
              <ul className="space-y-3">
                {candidates.map((candidate, index) => (
                  <li
                    key={`${candidate.name}-${index}`}
                    className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] p-3"
                  >
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checked[index] ?? false}
                        disabled={saving}
                        onChange={(event) =>
                          setChecked((prev) => {
                            const next = [...prev]
                            next[index] = event.target.checked
                            return next
                          })
                        }
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{candidate.name}</span>
                        {candidate.yrkesbakgrund ? (
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            {candidate.yrkesbakgrund}
                          </span>
                        ) : null}
                        {candidate.description ? (
                          <span className="mt-1 block text-sm text-muted-foreground">
                            {candidate.description}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <DialogFooter className="mx-0 mb-0 border-[color:var(--border-hairline)] bg-db-ink-0">
            <AdminButton variant="secondary" size="sm" disabled={saving} onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </AdminButton>
            {step === "review" ? (
              <AdminButton variant="primary" size="sm" disabled={saving} onClick={() => void addSelected()}>
                {saving ? t("tools.panelCatalog.suggestAdding") : t("tools.panelCatalog.suggestAdd")}
              </AdminButton>
            ) : (
              <AdminButton
                variant="primary"
                size="sm"
                disabled={step === "loading" || selectedId == null || rows.length === 0}
                onClick={() => void generate()}
              >
                {step === "loading"
                  ? t("tools.panelCatalog.suggestGenerating")
                  : t("tools.panelCatalog.suggestGenerate")}
              </AdminButton>
            )}
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
