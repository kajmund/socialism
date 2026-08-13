import { useEffect, useState } from "react"
import {
  getVerdictCalibration,
  saveVerdictCalibration,
  type VerdictCalibration,
} from "@/api/reports"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type Props = {
  reportId: string
}

export function ReportVerdictCalibrationPanel({ reportId }: Props) {
  const { t } = useLocale()
  const [data, setData] = useState<VerdictCalibration | null>(null)
  const [matches, setMatches] = useState<boolean | null>(null)
  const [note, setNote] = useState("")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    setSaved(false)
    void (async () => {
      try {
        const row = await getVerdictCalibration(reportId)
        if (cancelled) return
        setData(row)
        setMatches(row.matches)
        setNote(row.note ?? "")
      } catch (err) {
        if (cancelled) return
        setData(null)
        setLoadError(err instanceof ApiError ? err.message : t("reports.verdictCalibration.loadError"))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [reportId, t])

  async function onSave() {
    if (matches == null) {
      setSaveError(t("reports.verdictCalibration.choiceRequired"))
      return
    }
    setBusy(true)
    setSaveError(null)
    setSaved(false)
    try {
      const row = await saveVerdictCalibration(reportId, {
        matches,
        note: note.trim() || null,
      })
      setData(row)
      setMatches(row.matches)
      setNote(row.note ?? "")
      setSaved(true)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : t("reports.verdictCalibration.saveError"))
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <Card className="mb-4 gap-0 ring-1 ring-border">
        <CardContent className="px-5 py-4 text-sm text-muted-foreground">{loadError}</CardContent>
      </Card>
    )
  }

  if (!data?.recommendation) {
    return null
  }

  const rec = data.recommendation

  return (
    <Card className="mb-4 gap-0 ring-1 ring-border">
      <CardContent className="space-y-4 px-5 py-4">
        <div>
          <h2 className="text-base font-medium">{t("reports.verdictCalibration.title")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("reports.verdictCalibration.intro")}
          </p>
        </div>

        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t("reports.verdictCalibration.action")}</dt>
            <dd className="font-medium">{rec.action}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("reports.verdictCalibration.score")}</dt>
            <dd className="font-medium">{rec.score}/100</dd>
          </div>
          {rec.recommended_arm ? (
            <div>
              <dt className="text-muted-foreground">{t("reports.verdictCalibration.arm")}</dt>
              <dd className="font-medium">{rec.recommended_arm}</dd>
            </div>
          ) : null}
          <div>
            <dt className="text-muted-foreground">{t("reports.verdictCalibration.verdictKey")}</dt>
            <dd className="font-mono text-xs">{rec.verdict_key}</dd>
          </div>
        </dl>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("reports.verdictCalibration.question")}</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`verdict-match-${reportId}`}
                checked={matches === true}
                onChange={() => {
                  setMatches(true)
                  setSaved(false)
                }}
              />
              {t("reports.verdictCalibration.matchesYes")}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`verdict-match-${reportId}`}
                checked={matches === false}
                onChange={() => {
                  setMatches(false)
                  setSaved(false)
                }}
              />
              {t("reports.verdictCalibration.matchesNo")}
            </label>
          </div>
        </fieldset>

        <label className="grid gap-1 text-sm">
          <span>{t("reports.verdictCalibration.note")}</span>
          <textarea
            className="min-h-[4rem] w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={note}
            onChange={(e) => {
              setNote(e.target.value)
              setSaved(false)
            }}
            placeholder={t("reports.verdictCalibration.notePlaceholder")}
          />
        </label>

        {saveError ? (
          <p className="text-sm text-destructive" role="alert">
            {saveError}
          </p>
        ) : null}
        {saved ? (
          <p className="text-sm text-muted-foreground">{t("reports.verdictCalibration.saved")}</p>
        ) : null}

        <Button type="button" disabled={busy} onClick={() => void onSave()}>
          {busy ? t("reports.verdictCalibration.saving") : t("reports.verdictCalibration.save")}
        </Button>
      </CardContent>
    </Card>
  )
}
