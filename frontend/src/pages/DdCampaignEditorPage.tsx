import { useEffect, useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { createDdCampaign, getDdCampaign, updateDdCampaign, type DdCampaign } from "@/api/dd"
import { DdCampaignPanelSection } from "@/components/dd/DdCampaignPanelSection"
import { DdCampaignRunList } from "@/components/dd/DdCampaignRunList"
import { DdSourcingSearchModal } from "@/components/dd/DdSourcingSearchModal"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { primaryCampaignModuleId } from "@/modules/moduleRegistry"
import { useKundModules } from "@/modules/useKundModules"

type CampaignTab = "overview" | "candidates" | "run"

const TABS: readonly { id: CampaignTab; labelKey: MessageKey }[] = [
  { id: "overview", labelKey: "dd.campaigns.detail.tabOverview" },
  { id: "candidates", labelKey: "dd.campaigns.detail.tabCandidates" },
  { id: "run", labelKey: "dd.campaigns.detail.tabRun" },
]

function parseCampaignTab(raw: string | null): CampaignTab {
  if (raw === "candidates" || raw === "run") return raw
  return "overview"
}

function statusLabel(status: string, t: (key: MessageKey) => string): string {
  const key = `dd.campaigns.status.${status}` as MessageKey
  const translated = t(key)
  return translated === key ? status : translated
}

export function DdCampaignEditorPage() {
  const { t } = useLocale()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const isNew = !id || id === "new"
  const campaignId = isNew ? null : Number(id)
  const tab = parseCampaignTab(searchParams.get("tab"))

  const [title, setTitle] = useState("")
  const [campaign, setCampaign] = useState<DdCampaign | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const { moduleIds, loading: kundLoading } = useKundModules()
  const campaignModule = primaryCampaignModuleId(moduleIds)

  useEffect(() => {
    if (isNew || campaignId == null || Number.isNaN(campaignId)) return
    let cancelled = false
    setLoading(true)
    getDdCampaign(campaignId)
      .then((row) => {
        if (cancelled) return
        setCampaign(row)
        setTitle(row.title)
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

  function setTab(next: CampaignTab) {
    if (next === "overview") setSearchParams({}, { replace: true })
    else setSearchParams({ tab: next }, { replace: true })
  }

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(timer)
  }, [toast])

  if (!isNew && (campaignId == null || Number.isNaN(campaignId))) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  async function onCreateSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSaving(true)
    try {
      if (!campaignModule) {
        setError(t("dd.campaigns.detail.noCampaignModule"))
        return
      }
      const row = await createDdCampaign({ title: title.trim(), module: campaignModule })
      navigate(`/bolag/campaigns/${row.id}`, { replace: true })
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function onSaveTitle() {
    if (!campaign) return
    setError(null)
    setSaving(true)
    try {
      const row = await updateDdCampaign(campaign.id, { title: title.trim() })
      setCampaign(row)
      setToast(t("dd.campaigns.detail.saved"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.saveError"))
    } finally {
      setSaving(false)
    }
  }

  function renderOverview() {
    if (!campaign) return null
    return (
      <div id="campaign-tab-panel-overview" role="tabpanel" aria-labelledby="campaign-tab-overview">
        <form
          className="max-w-3xl space-y-6"
          onSubmit={(e) => {
            e.preventDefault()
            void onSaveTitle()
          }}
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium">{t("dd.campaigns.detail.nameLabel")}</span>
            <input
              className="dsearch"
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("dd.campaigns.detail.namePlaceholder")}
            />
          </label>
          <button type="submit" className="primary" disabled={saving || !title.trim()}>
            {saving ? t("dd.campaigns.detail.saving") : t("dd.campaigns.detail.save")}
          </button>
        </form>
      </div>
    )
  }

  if (loading || (!isNew && !campaign && !error)) {
    return (
      <div className="wrap admin-page">
        <div className="admin-page-body">
          <div className="no-match">{t("dd.campaigns.detail.loading")}</div>
        </div>
      </div>
    )
  }

  if (!isNew && !campaign) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  return (
    <>
      <div className="wrap admin-page">
        <div className="admin-page-chrome">
          <div className="crumb">
            <Link to="/bolag/campaigns">{t("dd.campaigns.detail.back")}</Link>
          </div>

          <div className="head-row">
            <div>
              <h1>{isNew ? t("dd.campaigns.detail.newTitle") : campaign?.title}</h1>
              {!isNew && campaign ? (
                <p>
                  {t("dd.campaigns.detail.intro", {
                    status: statusLabel(campaign.status, t),
                  })}
                </p>
              ) : (
                <p>{t("dd.campaigns.detail.newIntro")}</p>
              )}
            </div>
          </div>

          {error ? (
            <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }} role="alert">
              {error}
            </div>
          ) : null}

          {!isNew && campaign ? (
            <div
              role="tablist"
              aria-label={t("dd.campaigns.detail.tabsAria")}
              className="mb-4 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
            >
              {TABS.map(({ id, labelKey }) => {
                const selected = tab === id
                return (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    id={`campaign-tab-${id}`}
                    aria-selected={selected}
                    aria-controls={`campaign-tab-panel-${id}`}
                    tabIndex={selected ? 0 : -1}
                    className={cn(
                      "-mb-px border-b-2 px-3 py-2 text-sm",
                      selected
                        ? "border-db-ink-950 font-semibold text-[color:var(--text-body)]"
                        : "border-transparent font-normal text-muted-foreground hover:text-[color:var(--text-body)]",
                    )}
                    onClick={() => setTab(id)}
                  >
                    {t(labelKey)}
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>

        <div className="admin-page-body">
          {isNew ? (
            <form className="max-w-3xl space-y-6" onSubmit={onCreateSubmit}>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium">{t("dd.campaigns.detail.nameLabel")}</span>
                <input
                  className="dsearch"
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t("dd.campaigns.detail.namePlaceholder")}
                />
              </label>
              <button
                type="submit"
                className="primary"
                disabled={saving || kundLoading || !campaignModule || !title.trim()}
              >
                {saving ? t("dd.campaigns.detail.creating") : t("dd.campaigns.detail.create")}
              </button>
            </form>
          ) : null}

          {!isNew && campaign ? (
            <>
              <div hidden={tab !== "overview"}>{renderOverview()}</div>
              <div
                hidden={tab !== "candidates"}
                id="campaign-tab-panel-candidates"
                role="tabpanel"
                aria-labelledby="campaign-tab-candidates"
              >
                <DdCampaignPanelSection
                  campaign={campaign}
                  onOpenSearch={() => setSearchOpen(true)}
                />
              </div>
              <div
                hidden={tab !== "run"}
                id="campaign-tab-panel-run"
                role="tabpanel"
                aria-labelledby="campaign-tab-run"
              >
                <DdCampaignRunList campaign={campaign} onCampaignChange={setCampaign} />
              </div>
              {searchOpen ? (
                <DdSourcingSearchModal
                  open
                  campaign={campaign}
                  onClose={() => setSearchOpen(false)}
                  onAdded={(next) => {
                    const added = next.candidates.length - campaign.candidates.length
                    setCampaign(next)
                    setTab("candidates")
                    setToast(t("dd.sourcing.addDone", { count: added }))
                  }}
                />
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      ) : null}
    </>
  )
}
