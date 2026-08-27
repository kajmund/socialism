import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { listDdCampaigns, type DdCampaign } from "@/api/dd"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { formatLibraryDate } from "@/data/library"

function statusLabel(status: string, t: (key: MessageKey) => string): string {
  const key = `dd.campaigns.status.${status}` as MessageKey
  const translated = t(key)
  return translated === key ? status : translated
}

export function DdCampaignsPage() {
  const { t, intl } = useLocale()
  const [rows, setRows] = useState<DdCampaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listDdCampaigns("dd")
      .then((data) => {
        if (!cancelled) setRows(data)
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

  const grouped = useMemo(() => {
    const map = new Map<string, DdCampaign[]>()
    for (const row of rows) {
      const list = map.get(row.module) ?? []
      list.push(row)
      map.set(row.module, list)
    }
    return map
  }, [rows])

  return (
    <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("dd.campaigns.list.title")}</h1>
            <p className="intro">{t("dd.campaigns.list.intro")}</p>
          </div>
          <Link className="primary" to="/bolag/campaigns/new">
            {t("dd.campaigns.list.newCampaign")}
          </Link>
        </div>

        {loading ? <div className="no-match">{t("dd.campaigns.list.loading")}</div> : null}
        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        {!loading && !error && rows.length === 0 ? (
          <div className="no-match">{t("dd.campaigns.list.empty")}</div>
        ) : null}

        {[...grouped.entries()].map(([module, campaigns]) => (
          <section key={module} className="mb-10">
            <h2 className="mb-4 text-lg font-medium">{t("dd.campaigns.list.moduleHeading", { module })}</h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {campaigns.map((campaign) => (
                <Card key={campaign.id} className="gap-0 py-4 ring-1 ring-border">
                  <CardContent className="flex h-full flex-col gap-3 px-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium">{campaign.title}</div>
                      <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
                        {statusLabel(campaign.status, t)}
                      </span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {t("dd.campaigns.list.metaLine", {
                        candidates: campaign.candidates.length,
                        when: formatLibraryDate(campaign.updated_at, intl),
                      })}
                    </div>
                    <div className="mt-auto">
                      <Link className="primary" to={`/bolag/campaigns/${campaign.id}`}>
                        {t("common.open")}
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        ))}
    </div>
  )
}
