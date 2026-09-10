import { useLocale } from "@/i18n"

export type GenericPanelClaim = {
  claim_id: string
  claim: string
  evidence: string
  judgment: string
  score: number | null
  dissensus: boolean
  evidence_refs: string[]
}

export type GenericPanelPayload = {
  summary: string
  claims: GenericPanelClaim[]
  unanswered: string[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

export function parseGenericPanelPayload(
  payload: Record<string, unknown>,
): GenericPanelPayload | null {
  const claimsRaw = payload.claims
  if (payload.summary != null && typeof payload.summary !== "string") return null
  if (claimsRaw != null && !Array.isArray(claimsRaw)) return null
  if (payload.unanswered != null && !Array.isArray(payload.unanswered)) return null
  const claims: GenericPanelClaim[] = []
  for (const [index, raw] of (claimsRaw ?? []).entries()) {
    const row = asRecord(raw)
    if (row == null) continue
    const refs = Array.isArray(row.evidence_refs)
      ? row.evidence_refs.filter((item): item is string => typeof item === "string")
      : []
    const score = row.score
    claims.push({
      claim_id: readString(row.claim_id) || `claim-${index + 1}`,
      claim: readString(row.claim),
      evidence: readString(row.evidence),
      judgment: readString(row.judgment),
      score: typeof score === "number" && Number.isFinite(score) ? score : null,
      dissensus: row.dissensus === true,
      evidence_refs: refs,
    })
  }
  const unanswered = Array.isArray(payload.unanswered)
    ? payload.unanswered.filter((item): item is string => typeof item === "string")
    : []
  return {
    summary: readString(payload.summary),
    claims,
    unanswered,
  }
}

function EvidenceRefChip({
  citation,
  resolved,
  onSelect,
}: {
  citation: string
  resolved: boolean
  onSelect: (ref: string) => void
}) {
  const { t } = useLocale()
  if (!resolved) {
    return (
      <span
        data-evidence-ref={citation}
        data-unresolved="true"
        className="inline-flex items-center rounded-md border border-dashed border-[color:var(--border-hairline)] px-1.5 py-0.5 text-xs text-[color:var(--text-muted)]"
      >
        [{citation}] {t("execution.evidence.unresolved")}
      </span>
    )
  }
  return (
    <button
      type="button"
      data-evidence-ref={citation}
      className="inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium text-db-gold-700 underline"
      onClick={() => onSelect(citation)}
    >
      [{citation}]
    </button>
  )
}

function ClaimCard({
  claim,
  resolvedRefs,
  onSelectRef,
}: {
  claim: GenericPanelClaim
  resolvedRefs: ReadonlySet<string>
  onSelectRef: (ref: string) => void
}) {
  const { t } = useLocale()
  return (
    <article
      data-claim-id={claim.claim_id}
      data-dissensus={claim.dissensus ? "true" : "false"}
      className="rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3"
    >
      <p className="text-sm font-medium">{claim.claim || t("common.emDash")}</p>
      <dl className="mt-2 grid gap-2 text-sm">
        <div>
          <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
            {t("execution.result.evidence")}
          </dt>
          <dd className="mt-1 whitespace-pre-wrap">{claim.evidence || t("common.emDash")}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
            {t("execution.result.judgment")}
          </dt>
          <dd className="mt-1 whitespace-pre-wrap">{claim.judgment || t("common.emDash")}</dd>
        </div>
        {claim.score != null ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
              {t("execution.result.score")}
            </dt>
            <dd className="mt-1">{claim.score}</dd>
          </div>
        ) : null}
      </dl>
      {claim.evidence_refs.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {claim.evidence_refs.map((ref) => (
            <EvidenceRefChip
              key={ref}
              citation={ref}
              resolved={resolvedRefs.has(ref)}
              onSelect={onSelectRef}
            />
          ))}
        </div>
      ) : null}
    </article>
  )
}

export function GenericPanelResultView({
  payload,
  resolvedRefs,
  onSelectRef,
}: {
  payload: GenericPanelPayload
  resolvedRefs: ReadonlySet<string>
  onSelectRef: (ref: string) => void
}) {
  const { t } = useLocale()
  const claims = payload.claims.filter((claim) => !claim.dissensus)
  const dissensus = payload.claims.filter((claim) => claim.dissensus)
  return (
    <div className="grid gap-6">
      <section>
        <h3 className="text-sm font-medium">{t("execution.result.summary")}</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm">{payload.summary || t("common.emDash")}</p>
      </section>
      <section>
        <h3 className="text-sm font-medium">{t("execution.result.claims")}</h3>
        <div className="mt-2 grid gap-3">
          {claims.length === 0 ? (
            <p className="no-match m-0 text-left">{t("execution.result.claimsEmpty")}</p>
          ) : (
            claims.map((claim) => (
              <ClaimCard
                key={claim.claim_id}
                claim={claim}
                resolvedRefs={resolvedRefs}
                onSelectRef={onSelectRef}
              />
            ))
          )}
        </div>
      </section>
      <section>
        <h3 className="text-sm font-medium">{t("execution.result.dissensus")}</h3>
        <div className="mt-2 grid gap-3">
          {dissensus.length === 0 ? (
            <p className="no-match m-0 text-left">{t("execution.result.dissensusEmpty")}</p>
          ) : (
            dissensus.map((claim) => (
              <ClaimCard
                key={claim.claim_id}
                claim={claim}
                resolvedRefs={resolvedRefs}
                onSelectRef={onSelectRef}
              />
            ))
          )}
        </div>
      </section>
      <section>
        <h3 className="text-sm font-medium">{t("execution.result.unanswered")}</h3>
        {payload.unanswered.length === 0 ? (
          <p className="no-match mt-2 text-left">{t("execution.result.unansweredEmpty")}</p>
        ) : (
          <ul className="mt-2 list-disc pl-5 text-sm">
            {payload.unanswered.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
