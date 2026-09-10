import { useState } from "react"
import type { EvidenceSetItem } from "@/api/execution"
import { citationForFoundItem, evidenceItemDomId } from "@/components/execution/evidenceRefs"
import { JsonFallback } from "@/components/execution/JsonFallback"
import {
  evidenceItemStatusLabelKey,
  evidenceItemStatusTagClass,
  isEvidenceItemStatus,
} from "@/components/execution/status"
import { cn } from "@/lib/utils"
import { useLocale } from "@/i18n"

function usefulUrl(url: string | null): string | null {
  const text = (url ?? "").trim()
  return text.startsWith("http://") || text.startsWith("https://") ? text : null
}

export function EvidenceItemCard({
  item,
  items,
  highlighted,
}: {
  item: EvidenceSetItem
  items: readonly EvidenceSetItem[]
  highlighted: boolean
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const citation = citationForFoundItem(items, item.id)
  const statusLabel = isEvidenceItemStatus(item.status)
    ? t(evidenceItemStatusLabelKey(item.status))
    : item.status
  const href = usefulUrl(item.source_url)

  return (
    <article
      id={evidenceItemDomId(item.id)}
      data-evidence-item={item.id}
      data-evidence-status={item.status}
      data-evidence-ref={citation ?? undefined}
      data-highlighted={highlighted ? "true" : "false"}
      className={cn(
        "rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3",
        highlighted && "ring-2 ring-db-gold-500",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-sm font-medium">
          {citation ? <span className="mr-2 text-db-gold-700">[{citation}]</span> : null}
          {item.title || t("common.emDash")}
        </h3>
        <span className={evidenceItemStatusTagClass(item.status)}>{statusLabel}</span>
      </div>
      {item.excerpt ? (
        <p className="mt-2 whitespace-pre-wrap text-sm text-[color:var(--text-body)]">{item.excerpt}</p>
      ) : null}
      <dl className="mt-2 grid gap-1 text-xs text-[color:var(--text-muted)]">
        {item.locator ? (
          <div>
            {t("execution.evidence.locator")}: {item.locator}
          </div>
        ) : null}
        <div>
          {t("execution.evidence.sourceType")}: {item.source_type}
        </div>
        {item.provider ? (
          <div>
            {t("execution.evidence.provider")}: {item.provider}
          </div>
        ) : null}
      </dl>
      {href ? (
        <a
          className="mt-2 inline-block text-xs underline"
          href={href}
          target="_blank"
          rel="noreferrer"
        >
          {t("execution.evidence.sourceLink")}
        </a>
      ) : null}
      <div className="mt-3">
        <button
          type="button"
          className="text-xs underline"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? t("execution.evidence.hideProvenance") : t("execution.evidence.provenance")}
        </button>
        {open ? (
          <div className="mt-2 grid gap-1 text-xs text-[color:var(--text-muted)]">
            {item.provider ? <div>provider: {item.provider}</div> : null}
            {item.source_id ? <div>source_id: {item.source_id}</div> : null}
            {item.source_url ? <div>source_url: {item.source_url}</div> : null}
            {item.locator ? <div>locator: {item.locator}</div> : null}
            <div>retrieved_at: {item.retrieved_at}</div>
            <div>content_hash: {item.content_hash}</div>
            <JsonFallback value={item.provenance} />
          </div>
        ) : null}
      </div>
    </article>
  )
}
