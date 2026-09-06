import { useEffect, useRef, useState } from "react"
import { suggestExpertsFromUnderlag, type ExpertCandidate } from "@/api/personas"
import { UnderlagPicker, type UnderlagSelection } from "@/components/underlag/UnderlagPicker"
import { AdminButton } from "@/components/ui/admin-button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Step = "pick" | "loading" | "review"

const UNDERLAG_MODULE = "expertgranskning"

export function SuggestExpertsModal({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (candidates: ExpertCandidate[]) => Promise<void>
}) {
  const { t } = useLocale()
  const [step, setStep] = useState<Step>("pick")
  const [selected, setSelected] = useState<UnderlagSelection | null>(null)
  const [candidates, setCandidates] = useState<ExpertCandidate[]>([])
  const [checked, setChecked] = useState<boolean[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestGen = useRef(0)

  useEffect(() => {
    if (!open) {
      requestGen.current += 1
      setStep("pick")
      setSelected(null)
      setCandidates([])
      setChecked([])
      setSaving(false)
      setError(null)
    }
  }, [open])

  async function generate() {
    if (selected == null || selected.status !== "ok") {
      setError(t("experts.suggest.needUnderlag"))
      return
    }
    const token = ++requestGen.current
    setStep("loading")
    setError(null)
    try {
      const suggested = await suggestExpertsFromUnderlag({
        underlag_id: selected.objectId,
        module: UNDERLAG_MODULE,
      })
      if (token !== requestGen.current) return
      setCandidates(suggested)
      setChecked(suggested.map(() => true))
      setStep("review")
    } catch (err: unknown) {
      if (token !== requestGen.current) return
      setError(err instanceof ApiError ? err.message : t("experts.suggest.error"))
      setStep("pick")
    }
  }

  async function addSelected() {
    const chosen = candidates.filter((_, index) => checked[index])
    if (chosen.length === 0) {
      setError(t("experts.suggest.needCandidate"))
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onConfirm(chosen)
      onOpenChange(false)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("experts.suggest.saveError"))
    } finally {
      setSaving(false)
    }
  }

  const canGenerate = selected != null && selected.status === "ok" && step !== "loading"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="theme-admin max-h-[min(880px,92vh)] w-full max-w-2xl overflow-hidden bg-db-ink-0 p-0 sm:max-w-2xl"
        showCloseButton={false}
      >
        <div className="flex max-h-[min(880px,92vh)] flex-col">
          <DialogHeader className="border-b border-[color:var(--border-hairline)] px-5 py-4">
            <DialogTitle>{t("experts.suggest.title")}</DialogTitle>
            <DialogDescription>{t("experts.suggest.intro")}</DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {error ? (
              <p className="mb-3 text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}

            {step === "pick" || step === "loading" ? (
              <div className="space-y-3">
                <UnderlagPicker
                  module={UNDERLAG_MODULE}
                  value={selected}
                  disabled={step === "loading"}
                  onChange={(next) => {
                    setSelected(next)
                    setError(null)
                  }}
                />
                {step === "loading" ? (
                  <p className="text-sm text-muted-foreground">{t("experts.suggest.generating")}</p>
                ) : null}
              </div>
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
                {saving ? t("experts.suggest.adding") : t("experts.suggest.add")}
              </AdminButton>
            ) : (
              <AdminButton
                variant="primary"
                size="sm"
                disabled={!canGenerate}
                onClick={() => void generate()}
              >
                {step === "loading" ? t("experts.suggest.generating") : t("experts.suggest.generate")}
              </AdminButton>
            )}
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
