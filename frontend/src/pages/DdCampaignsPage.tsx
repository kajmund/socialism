import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteDdCampaign, listDdCampaigns, type DdCampaign } from "@/api/dd"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { formatLibraryDate } from "@/data/library"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

const CTA_CLASS =
  "admin-cta inline-flex h-9 items-center rounded-[var(--radius-md)] bg-db-black px-[18px] text-[0.85rem] text-db-ink-0 no-underline hover:bg-db-ink-800"

function statusLabel(status: string, t: Translate): string {
  const key = `dd.campaigns.status.${status}` as MessageKey
  const translated = t(key)
  return translated === key ? status : translated
}

type CampaignItemProps = {
  campaign: DdCampaign
  intl: string
  t: Translate
  onDelete: (id: number) => void
}

function CampaignCard({ campaign, intl, t, onDelete }: CampaignItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{campaign.title}</div>
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {statusLabel(campaign.status, t)}
            </span>
          </div>
          <div className="meta-line">
            {t("dd.campaigns.list.metaLine", {
              candidates: campaign.candidates.length,
              when: formatLibraryDate(campaign.updated_at, intl),
            })}
          </div>
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: "auto" }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(campaign.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions" style={{ marginTop: "auto" }}>
              <Link className="primary" to={`/bolag/campaigns/${campaign.id}`}>
                {t("common.open")}
              </Link>
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                {t("common.delete")}
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function CampaignListRow({ campaign, intl, t, onDelete }: CampaignItemProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="admin-list-row admin-list-pops">
      <div>
        <div className="nm">{campaign.title}</div>
        <div className="meta">
          {t("dd.campaigns.list.metaLine", {
            candidates: campaign.candidates.length,
            when: formatLibraryDate(campaign.updated_at, intl),
          })}
        </div>
      </div>
      <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
        {statusLabel(campaign.status, t)}
      </span>
      <div className="admin-list-actions">
        {confirming ? (
          <>
            <button type="button" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
            <button type="button" className="primary" onClick={() => onDelete(campaign.id)}>
              {t("common.deleteConfirm")}
            </button>
          </>
        ) : (
          <>
            <Link className="primary" to={`/bolag/campaigns/${campaign.id}`}>
              {t("common.open")}
            </Link>
            <button type="button" onClick={() => setConfirming(true)}>
              {t("common.delete")}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export function DdCampaignsPage() {
  const { t, intl } = useLocale()
  const [rows, setRows] = useState<DdCampaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listDdCampaigns({ module: "dd" })
      .then((data) => {
        if (!cancelled) {
          setRows(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("dd.campaigns.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [toast])

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows
      .filter((row) => !q || row.title.toLowerCase().includes(q))
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
  }, [rows, query])

  async function handleDelete(id: number) {
    try {
      await deleteDdCampaign(id)
      setRows((prev) => prev.filter((row) => row.id !== id))
      setToast(t("dd.campaigns.list.deleted"))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  return (
    <div className="wrap">
      <div className="head-row">
        <div>
          <h1>{t("dd.campaigns.list.title")}</h1>
          <p>{t("dd.campaigns.list.intro")}</p>
        </div>
      </div>

      {error ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="no-match">{t("dd.campaigns.list.loading")}</div>
      ) : rows.length > 0 ? (
        <>
          <div className="controls-row">
            <div className="controls-left">
              <input
                className="dsearch"
                placeholder={t("dd.campaigns.list.searchPlaceholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="controls-right">
              <ViewToggle value={view} onChange={setView} />
              <Link to="/bolag/campaigns/new" className={CTA_CLASS}>
                {t("dd.campaigns.list.newCampaign")}
              </Link>
            </div>
          </div>
          {list.length === 0 ? (
            <div className="no-match">{t("dd.campaigns.list.emptyFilter", { query })}</div>
          ) : view === "grid" ? (
            <div className="pop-grid">
              {list.map((campaign) => (
                <CampaignCard
                  key={campaign.id}
                  campaign={campaign}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          ) : (
            <div className="admin-list-stack">
              {list.map((campaign) => (
                <CampaignListRow
                  key={campaign.id}
                  campaign={campaign}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <h2 style={{ font: "var(--text-h2)", marginBottom: 10 }}>
            {t("dd.campaigns.list.emptyTitle")}
          </h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>
            {t("dd.campaigns.list.emptyBody")}
          </p>
          <Link to="/bolag/campaigns/new" className={CTA_CLASS}>
            {t("dd.campaigns.list.newCampaign")}
          </Link>
        </div>
      )}

      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      ) : null}
    </div>
  )
}
