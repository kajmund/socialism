import { useMemo } from "react"
import type { DdCampaign, DdCandidateCompany } from "@/api/dd"
import { DdCandidateFacts } from "@/components/dd/DdCandidateFacts"
import { useLocale } from "@/i18n"

function candidateKey(candidate: DdCandidateCompany): string {
  return candidate.organisationsnummer || candidate.id
}

export function DdCampaignPanelSection({
  campaign,
  onOpenSearch,
}: {
  campaign: DdCampaign
  onOpenSearch: () => void
}) {
  const { t } = useLocale()
  const uniqueCandidates = useMemo(() => {
    const seen = new Set<string>()
    return campaign.candidates.filter((candidate) => {
      const key = candidateKey(candidate)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [campaign.candidates])

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
      <p className="text-sm text-[var(--color-muted)]">{t("dd.panel.candidatesIntro")}</p>

      {uniqueCandidates.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">{t("dd.sourcing.candidatesEmpty")}</p>
      ) : (
        <ul className="space-y-3">
          {uniqueCandidates.map((candidate) => (
            <li
              key={candidate.id}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
            >
              <p className="font-medium text-[var(--color-text)]">{candidate.namn}</p>
              <p className="mt-1 text-xs text-[var(--color-muted)]">
                {candidate.organisationsnummer || "—"}
              </p>
              <DdCandidateFacts candidate={candidate} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
