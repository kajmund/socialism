import { useEffect, useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import {
  createDdCampaign,
  defaultDdCriteria,
  getDdCampaign,
  runDdCampaignSourcing,
  updateDdCampaign,
  type DdCampaign,
  type DdCandidateCompany,
  type DdResultatFilter,
  type DdSourcingCriteria,
} from "@/api/dd"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

const RESULTAT_OPTIONS: DdResultatFilter[] = ["oavsett", "vinst", "förlust"]

function CriteriaForm({
  criteria,
  onChange,
  disabled,
}: {
  criteria: DdSourcingCriteria
  onChange: (next: DdSourcingCriteria) => void
  disabled?: boolean
}) {
  const { t } = useLocale()

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.alderMin")}</span>
        <input
          type="number"
          min={0}
          max={200}
          value={criteria.alder_min}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, alder_min: Number(e.target.value) })}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.alderMax")}</span>
        <input
          type="number"
          min={0}
          max={200}
          value={criteria.alder_max}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, alder_max: Number(e.target.value) })}
        />
      </label>
      <label className="flex flex-col gap-1.5 md:col-span-2">
        <span className="text-xs font-medium">{t("dd.sourcing.omrade")}</span>
        <input
          type="text"
          value={criteria.omrade}
          disabled={disabled}
          placeholder={t("dd.sourcing.omradePlaceholder")}
          onChange={(e) => onChange({ ...criteria, omrade: e.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.resultat")}</span>
        <select
          value={criteria.resultat}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, resultat: e.target.value as DdResultatFilter })}
        >
          {RESULTAT_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {t(`dd.sourcing.resultatOptions.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 md:col-span-2">
        <span className="text-xs font-medium">{t("dd.sourcing.fritext")}</span>
        <textarea
          rows={3}
          value={criteria.fritext}
          disabled={disabled}
          placeholder={t("dd.sourcing.fritextPlaceholder")}
          onChange={(e) => onChange({ ...criteria, fritext: e.target.value })}
        />
      </label>
    </div>
  )
}

function CandidateList({ candidates }: { candidates: DdCandidateCompany[] }) {
  const { t, intl } = useLocale()
  if (candidates.length === 0) return null

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-lg font-medium">{t("dd.sourcing.candidatesTitle")}</h2>
      <div className="grid gap-3">
        {candidates.map((c) => (
          <div
            key={c.id}
            className="rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 p-4"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="font-medium">{c.namn}</div>
              <div className="text-xs text-muted-foreground">{c.organisationsnummer}</div>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{c.beskrivning}</p>
            <dl className="mt-3 grid gap-1 text-sm md:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  {t("dd.sourcing.candidateAge")}
                </dt>
                <dd>{t("dd.sourcing.candidateAgeValue", { years: c.alder_ar })}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  {t("dd.sourcing.candidateRegion")}
                </dt>
                <dd>{c.omrade}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  {t("dd.sourcing.candidateResult")}
                </dt>
                <dd>{t(`dd.sourcing.resultatOptions.${c.resultat}`)}</dd>
              </div>
              {c.omsattning_sek != null ? (
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    {t("dd.sourcing.candidateRevenue")}
                  </dt>
                  <dd>{new Intl.NumberFormat(intl).format(c.omsattning_sek)} SEK</dd>
                </div>
              ) : null}
            </dl>
          </div>
        ))}
      </div>
    </div>
  )
}

export function DdCampaignEditorPage() {
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isNew = !id || id === "new"
  const campaignId = isNew ? null : Number(id)

  const [title, setTitle] = useState("")
  const [criteria, setCriteria] = useState<DdSourcingCriteria>(defaultDdCriteria())
  const [campaign, setCampaign] = useState<DdCampaign | null>(null)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [sourcing, setSourcing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (isNew || campaignId == null || Number.isNaN(campaignId)) return
    let cancelled = false
    setLoading(true)
    getDdCampaign(campaignId)
      .then((row) => {
        if (cancelled) return
        setCampaign(row)
        setTitle(row.title)
        setCriteria(row.criteria)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [campaignId, isNew, t])

  if (!isNew && (campaignId == null || Number.isNaN(campaignId))) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  async function onCreateSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const row = await createDdCampaign({ title: title.trim(), criteria })
      navigate(`/bolag/campaigns/${row.id}`, { replace: true })
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onSaveCriteria() {
    if (!campaign) return
    setError(null)
    setSaving(true)
    try {
      const row = await updateDdCampaign(campaign.id, { title: title.trim(), criteria })
      setCampaign(row)
      setToast(t("dd.campaigns.detail.saved"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onRunSourcing() {
    if (!campaign) return
    setError(null)
    setSourcing(true)
    try {
      if (title.trim() !== campaign.title || JSON.stringify(criteria) !== JSON.stringify(campaign.criteria)) {
        await updateDdCampaign(campaign.id, { title: title.trim(), criteria })
      }
      const row = await runDdCampaignSourcing(campaign.id)
      setCampaign(row)
      setCriteria(row.criteria)
      setToast(t("dd.sourcing.runDone", { count: row.candidates.length }))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.sourcing.runError"))
    } finally {
      setSourcing(false)
    }
  }

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(timer)
  }, [toast])

  if (loading) {
    return (
      <div className="wrap">
        <div className="no-match">{t("dd.campaigns.detail.loading")}</div>
      </div>
    )
  }

  if (!isNew && !campaign && !loading) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  return (
    <>
      <div className="wrap wrap-full">
        <div className="crumb">
          <Link to="/bolag/campaigns">{t("dd.campaigns.detail.back")}</Link>
        </div>

        <div className="head-row">
          <div>
            <h1>{isNew ? t("dd.campaigns.detail.newTitle") : t("dd.campaigns.detail.title")}</h1>
            {!isNew && campaign ? (
              <p className="intro">{t("dd.campaigns.detail.intro", { status: campaign.status })}</p>
            ) : (
              <p className="intro">{t("dd.campaigns.detail.newIntro")}</p>
            )}
          </div>
        </div>

        {error ? (
          <p className="mb-4 text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        <form className="max-w-3xl space-y-6" onSubmit={isNew ? onCreateSubmit : (e) => e.preventDefault()}>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium">{t("dd.campaigns.detail.nameLabel")}</span>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("dd.campaigns.detail.namePlaceholder")}
            />
          </label>

          <section>
            <h2 className="mb-3 text-lg font-medium">{t("dd.sourcing.sectionTitle")}</h2>
            <p className="mb-4 text-sm text-muted-foreground">{t("dd.sourcing.sectionIntro")}</p>
            <CriteriaForm criteria={criteria} onChange={setCriteria} disabled={saving || sourcing} />
          </section>

          <div className="flex flex-wrap gap-3">
            {isNew ? (
              <button type="submit" className="primary" disabled={saving || !title.trim()}>
                {saving ? t("dd.campaigns.detail.creating") : t("dd.campaigns.detail.create")}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="primary"
                  disabled={saving || sourcing}
                  onClick={() => void onSaveCriteria()}
                >
                  {saving ? t("dd.campaigns.detail.saving") : t("dd.campaigns.detail.save")}
                </button>
                <button type="button" disabled={saving || sourcing} onClick={() => void onRunSourcing()}>
                  {sourcing ? t("dd.sourcing.running") : t("dd.sourcing.run")}
                </button>
              </>
            )}
          </div>
        </form>

        {!isNew && campaign ? <CandidateList candidates={campaign.candidates} /> : null}
      </div>

      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      ) : null}
    </>
  )
}
