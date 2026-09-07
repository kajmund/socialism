import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  getRattsunderlagResearch,
  listRattsunderlagResearch,
  resultFromJob,
  startRattsunderlagResearch,
  type ForarbeteRef,
  type LagtextRef,
  type PraxisRef,
  type RattsunderlagJob,
  type SourcingStatus,
} from "@/api/rattsunderlag"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type ResultTab = "law" | "praxis" | "travaux"

function statusKey(status: SourcingStatus): MessageKey {
  switch (status) {
    case "complete":
      return "rattsunderlag.status.complete"
    case "partial":
      return "rattsunderlag.status.partial"
    case "no_sources_found":
      return "rattsunderlag.status.none"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function jobStatusKey(status: RattsunderlagJob["status"]): MessageKey {
  switch (status) {
    case "pending":
      return "jobs.status.pending"
    case "running":
      return "jobs.status.running"
    case "succeeded":
      return "jobs.status.succeeded"
    case "failed":
      return "jobs.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function SourceCard({
  heading,
  body,
  href,
}: {
  heading: string
  body: string
  href?: string | null
}) {
  return (
    <article className="rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3">
      <h3 className="text-sm font-medium">{heading}</h3>
      {body ? <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{body}</p> : null}
      {href ? (
        <a className="mt-2 inline-block text-xs underline" href={href} target="_blank" rel="noreferrer">
          {href}
        </a>
      ) : null}
    </article>
  )
}

function LawList({ rows }: { rows: LagtextRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.sfs_id}
          heading={row.rubrik ? `${row.sfs_id} — ${row.rubrik}` : row.sfs_id}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

function PraxisList({ rows }: { rows: PraxisRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.referens}
          heading={row.instans ? `${row.referens} (${row.instans})` : row.referens}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

function TravauxList({ rows }: { rows: ForarbeteRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.referens}
          heading={row.titel ? `${row.referens} — ${row.titel}` : row.referens}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

export function RattsunderlagPage() {
  const { t, locale } = useLocale()
  const navigate = useNavigate()
  const { jobId } = useParams<{ jobId?: string }>()
  const [fraga, setFraga] = useState("")
  const [jobs, setJobs] = useState<RattsunderlagJob[]>([])
  const [active, setActive] = useState<RattsunderlagJob | null>(null)
  const [tab, setTab] = useState<ResultTab>("law")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    listRattsunderlagResearch()
      .then((rows) => {
        if (!cancelled) setJobs(rows)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("rattsunderlag.loadError"))
        }
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!jobId) {
      setActive(null)
      return
    }
    let cancelled = false
    getRattsunderlagResearch(jobId)
      .then((row) => {
        if (!cancelled) setActive(row)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("rattsunderlag.loadError"))
        }
      })
    return () => {
      cancelled = true
    }
  }, [jobId, t])

  useEffect(() => {
    if (!active || (active.status !== "pending" && active.status !== "running")) return
    const timer = window.setInterval(() => {
      getRattsunderlagResearch(active.id)
        .then((row) => {
          setActive(row)
          setJobs((current) => current.map((item) => (item.id === row.id ? row : item)))
        })
        .catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [active])

  const result = active ? resultFromJob(active) : null
  const emptyLabel = useMemo(() => {
    switch (tab) {
      case "law":
        return t("rattsunderlag.emptyLaw")
      case "praxis":
        return t("rattsunderlag.emptyPraxis")
      case "travaux":
        return t("rattsunderlag.emptyTravaux")
      default: {
        const _exhaustive: never = tab
        return _exhaustive
      }
    }
  }, [t, tab])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const question = fraga.trim()
    if (!question) {
      setError(t("rattsunderlag.missingQuestion"))
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const job = await startRattsunderlagResearch({
        fraga: question,
        locale: locale === "en" ? "en" : "sv",
      })
      setJobs((current) => [job, ...current.filter((row) => row.id !== job.id)])
      setActive(job)
      setFraga("")
      navigate(`/rattsunderlag/${job.id}`)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("rattsunderlag.startError"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AdminShell>
      <div className="wrap admin-page">
        <div className="admin-page-chrome">
          <span className="kicker">{t("modules.rattsunderlag.name")}</span>
          <h1>{t("rattsunderlag.title")}</h1>
          <p className="explainer">{t("rattsunderlag.intro")}</p>
        </div>
        <div className="admin-page-body grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <section className="grid gap-4">
            <form className="grid gap-3" onSubmit={(event) => void onSubmit(event)}>
              <label htmlFor="rattsunderlag-fraga">{t("rattsunderlag.questionLabel")}</label>
              <textarea
                id="rattsunderlag-fraga"
                rows={6}
                value={fraga}
                onChange={(event) => setFraga(event.target.value)}
                placeholder={t("rattsunderlag.questionPlaceholder")}
              />
              <AdminButton type="submit" disabled={submitting}>
                {submitting ? t("rattsunderlag.starting") : t("rattsunderlag.start")}
              </AdminButton>
            </form>
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <div>
              <h2 className="mb-2 text-sm font-medium">{t("rattsunderlag.historyTitle")}</h2>
              {jobs.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("rattsunderlag.historyEmpty")}</p>
              ) : (
                <ul className="grid gap-2">
                  {jobs.map((job) => (
                    <li key={job.id}>
                      <Link
                        className="block rounded-md border border-[color:var(--border-hairline)] px-3 py-2 text-sm hover:bg-muted/40"
                        to={`/rattsunderlag/${job.id}`}
                      >
                        <span className="block truncate">{job.label}</span>
                        <span className="text-xs text-muted-foreground">{t(jobStatusKey(job.status))}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
          <section className="grid gap-4">
            {!active ? (
              <p className="text-sm text-muted-foreground">{t("rattsunderlag.resultEmpty")}</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">{t(jobStatusKey(active.status))}</span>
                  {result ? <span className="text-sm">{t(statusKey(result.sourcing_status))}</span> : null}
                </div>
                {active.status === "failed" && active.error ? (
                  <p className="text-sm text-destructive">{active.error}</p>
                ) : null}
                {result ? (
                  <>
                    <div>
                      <h2 className="text-sm font-medium">{t("rattsunderlag.assessment")}</h2>
                      <p className="mt-2 whitespace-pre-wrap text-sm">{result.sammanfattning}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(
                        [
                          ["law", "rattsunderlag.tabLaw"],
                          ["praxis", "rattsunderlag.tabPraxis"],
                          ["travaux", "rattsunderlag.tabTravaux"],
                        ] as const
                      ).map(([id, key]) => (
                        <AdminButton
                          key={id}
                          type="button"
                          size="sm"
                          variant={tab === id ? "default" : "secondary"}
                          onClick={() => setTab(id)}
                        >
                          {t(key)}
                        </AdminButton>
                      ))}
                    </div>
                    {tab === "law" ? (
                      result.lagtext.length ? (
                        <LawList rows={result.lagtext} />
                      ) : (
                        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
                      )
                    ) : null}
                    {tab === "praxis" ? (
                      result.praxis.length ? (
                        <PraxisList rows={result.praxis} />
                      ) : (
                        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
                      )
                    ) : null}
                    {tab === "travaux" ? (
                      result.forarbeten.length ? (
                        <TravauxList rows={result.forarbeten} />
                      ) : (
                        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
                      )
                    ) : null}
                    <div className="flex flex-wrap gap-3">
                      {active.result?.report_id ? (
                        <Link className="text-sm underline" to={`/reports/${active.result.report_id}`}>
                          {t("rattsunderlag.openReport")}
                        </Link>
                      ) : null}
                      <Link className="text-sm underline" to="/expertgranskning/new">
                        {t("rattsunderlag.sendToReview")}
                      </Link>
                    </div>
                  </>
                ) : null}
              </>
            )}
          </section>
        </div>
      </div>
    </AdminShell>
  )
}
