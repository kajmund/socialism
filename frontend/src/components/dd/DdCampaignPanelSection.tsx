import { useMemo, useState } from "react"
import { ChevronDown } from "lucide-react"
import type { DdCampaign, DdCandidateCompany } from "@/api/dd"
import { DdCandidateAnnualReports } from "@/components/dd/DdCandidateAnnualReports"
import { DdCandidateFacts } from "@/components/dd/DdCandidateFacts"
import { useLocale } from "@/i18n"
import { cn } from "@/lib/utils"

function candidateKey(candidate: DdCandidateCompany): string {
  return candidate.organisationsnummer || candidate.id
}

function formatSek(value: number | null | undefined, intl: string): string {
  if (value == null) return "—"
  return `${new Intl.NumberFormat(intl).format(value)} kr`
}

export function DdCampaignPanelSection({
  campaign,
  onOpenSearch,
}: {
  campaign: DdCampaign
  onOpenSearch: () => void
}) {
  const { t, intl } = useLocale()
  const uniqueCandidates = useMemo(() => {
    const seen = new Set<string>()
    return campaign.candidates.filter((candidate) => {
      const key = candidateKey(candidate)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [campaign.candidates])
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set())

  function toggle(id: string) {
    setOpenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-lg font-semibold text-gold">
          {t("dd.sourcing.candidatesTitle")}
        </h2>
        <button type="button" className="primary" onClick={onOpenSearch}>
          {t("dd.campaigns.detail.openSearch")}
        </button>
      </div>
      <p className="text-sm text-[var(--text-muted)]">{t("dd.panel.candidatesIntro")}</p>

      {uniqueCandidates.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">{t("dd.sourcing.candidatesEmpty")}</p>
      ) : (
        <ul className="space-y-3">
          {uniqueCandidates.map((candidate) => {
            const open = openIds.has(candidate.id)
            const panelId = `candidate-facts-${candidate.id}`
            return (
              <li
                key={candidate.id}
                className="rounded-lg border border-[color:var(--border-hairline)] bg-[var(--surface-page)]"
              >
                <button
                  type="button"
                  className="flex w-full items-start gap-3 px-4 py-3 text-left"
                  aria-expanded={open}
                  aria-controls={panelId}
                  aria-label={
                    open
                      ? t("dd.sourcing.collapseCandidate", { name: candidate.namn })
                      : t("dd.sourcing.expandCandidate", { name: candidate.namn })
                  }
                  onClick={() => toggle(candidate.id)}
                >
                  <ChevronDown
                    className={cn(
                      "mt-1 size-4 shrink-0 text-[var(--text-muted)] transition-transform",
                      open ? "rotate-0" : "-rotate-90",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-[var(--text-body)]">
                      {candidate.namn}
                    </span>
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                      {candidate.organisationsnummer || "—"}
                      {" · "}
                      {t("dd.sourcing.candidateRevenue")}: {formatSek(candidate.omsattning_sek, intl)}
                      {" · "}
                      {t("dd.sourcing.candidateEmployees")}: {candidate.anstallda ?? "—"}
                    </span>
                  </span>
                </button>
                {open ? (
                  <div id={panelId} className="border-t border-[color:var(--border-hairline)] px-4 py-4">
                    <DdCandidateAnnualReports campaignId={campaign.id} candidateId={candidate.id} />
                    <DdCandidateFacts candidate={candidate} />
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
