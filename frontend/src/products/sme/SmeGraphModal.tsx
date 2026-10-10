import { Network, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import {
  getOvergraphNode,
  listOvergraphCatalogs,
  listOvergraphNodes,
  type OvergraphCatalog,
  type OvergraphEdge,
  type OvergraphKind,
  type OvergraphNode,
  type OvergraphNodeDetail,
} from "@/api/overgraph"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"

const PAGE_SIZE = 40

function catalogName(kind: OvergraphKind, t: (key: "sme.graphKnowledge" | "sme.graphMemory") => string): string {
  switch (kind) {
    case "knowledge":
      return t("sme.graphKnowledge")
    case "memory":
      return t("sme.graphMemory")
    default: {
      const exhaustive: never = kind
      return exhaustive
    }
  }
}

function formatWhen(value: number | null, locale: string): string | null {
  if (value == null) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function formatProp(value: unknown): string {
  if (typeof value === "string") return value
  if (value == null) return ""
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return JSON.stringify(value, null, 2)
}

export function SmeGraphModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, intl } = useLocale()
  const [catalogs, setCatalogs] = useState<OvergraphCatalog[]>([])
  const [kind, setKind] = useState<OvergraphKind>("knowledge")
  const [label, setLabel] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [debounced, setDebounced] = useState("")
  const [nodes, setNodes] = useState<OvergraphNode[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<OvergraphNodeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const kindRef = useRef(kind)
  const listEpoch = useRef(0)
  kindRef.current = kind

  useEffect(() => {
    if (!open) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [onClose, open])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(null)
    void listOvergraphCatalogs().then((result) => {
      if (cancelled) return
      setCatalogs(result.catalogs)
      const currentKind = kindRef.current
      const catalog = result.catalogs.find((row) => row.kind === currentKind) ?? result.catalogs[0]
      if (catalog && catalog.kind !== currentKind) setKind(catalog.kind)
      setLabel((selected) => (
        selected && catalog?.node_labels.some((row) => row.label === selected)
          ? selected
          : catalog?.node_labels[0]?.label ?? null
      ))
    }).catch(() => {
      if (!cancelled) setError(t("sme.graphLoadError"))
    })
    return () => { cancelled = true }
  }, [open, t])

  useEffect(() => {
    if (!open || !label) {
      setNodes([])
      setCursor(null)
      return
    }
    const epoch = ++listEpoch.current
    setLoading(true)
    setLoadingMore(false)
    setError(null)
    void listOvergraphNodes(kind, { label, q: debounced, limit: PAGE_SIZE }).then((page) => {
      if (listEpoch.current !== epoch) return
      setNodes(page.nodes)
      setCursor(page.next_cursor)
    }).catch(() => {
      if (listEpoch.current === epoch) setError(t("sme.graphLoadError"))
    }).finally(() => {
      if (listEpoch.current === epoch) setLoading(false)
    })
    return () => { listEpoch.current += 1 }
  }, [debounced, kind, label, open, t])

  useEffect(() => {
    if (!open || selectedId == null) {
      setDetail(null)
      return
    }
    let cancelled = false
    void getOvergraphNode(kind, selectedId).then((node) => {
      if (!cancelled) setDetail(node)
    }).catch(() => {
      if (!cancelled) setError(t("sme.graphLoadError"))
    })
    return () => { cancelled = true }
  }, [kind, open, selectedId, t])

  if (!open) return null

  const catalog = catalogs.find((row) => row.kind === kind)
  const outgoing = detail?.edges.filter((edge) => edge.direction === "outgoing") ?? []
  const incoming = detail?.edges.filter((edge) => edge.direction === "incoming") ?? []

  function chooseKind(next: OvergraphKind) {
    const nextCatalog = catalogs.find((row) => row.kind === next)
    setKind(next)
    setLabel(nextCatalog?.node_labels[0]?.label ?? null)
    setQuery("")
    setDebounced("")
    setSelectedId(null)
    setDetail(null)
  }

  function chooseLabel(next: string) {
    setLabel(next)
    setSelectedId(null)
    setDetail(null)
  }

  async function more() {
    if (!label || cursor == null || loadingMore) return
    const epoch = listEpoch.current
    setLoadingMore(true)
    try {
      const page = await listOvergraphNodes(kind, { label, q: debounced, limit: PAGE_SIZE, after: cursor })
      if (listEpoch.current !== epoch) return
      setNodes((current) => [...current, ...page.nodes])
      setCursor(page.next_cursor)
    } finally {
      if (listEpoch.current === epoch) setLoadingMore(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sme-graph-modal-title"
      onClick={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <div className="flex h-[min(94vh,960px)] w-full max-w-7xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-white/15 bg-db-ink-0 text-db-ink-950 shadow-2xl">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--border-hairline)] bg-db-ink-950 px-4 text-db-ink-0">
          <Network size={18} className="text-db-gold-500" aria-hidden="true" />
          <h2 id="sme-graph-modal-title" className="text-sm font-medium">{t("sme.graphTitle")}</h2>
          <AdminButton variant="accent" size="sm" className="ml-auto gap-1.5" onClick={onClose}>
            <X size={15} aria-hidden="true" />
            {t("sme.closeGraph")}
          </AdminButton>
        </header>
        {error ? <p className="shrink-0 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive" role="alert">{error}</p> : null}
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
          <aside className="flex max-h-56 flex-col overflow-y-auto border-b border-[color:var(--border-hairline)] lg:max-h-none lg:border-b-0 lg:border-r">
            <div className="flex gap-1 p-3" role="group" aria-label={t("sme.graphTitle")}>
              {(["knowledge", "memory"] as const).map((item) => (
                <button key={item} type="button" aria-pressed={kind === item} className={`flex-1 rounded-md px-2 py-1.5 text-xs ${kind === item ? "bg-db-ink-950 font-medium text-db-gold-500" : "bg-db-ink-100 hover:bg-white"}`} onClick={() => chooseKind(item)}>
                  {catalogName(item, t)}
                </button>
              ))}
            </div>
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">{t("sme.graphLabels")}</p>
            {catalog && catalog.node_labels.length === 0 ? <p className="px-3 py-2 text-sm text-[color:var(--text-muted)]">{t("sme.graphEmptyCatalog")}</p> : null}
            <ul>
              {catalog?.node_labels.map((row) => (
                <li key={row.label}>
                  <button type="button" aria-pressed={label === row.label} className={`flex w-full items-baseline justify-between gap-2 border-l-2 px-3 py-2 text-left text-sm ${label === row.label ? "border-db-gold-500 bg-db-gold-100" : "border-transparent hover:bg-db-ink-50"}`} onClick={() => chooseLabel(row.label)}>
                    <span className="truncate">{row.label}</span>
                    <span className="shrink-0 text-xs text-[color:var(--text-muted)]">{row.count}</span>
                  </button>
                </li>
              ))}
            </ul>
            {catalog && catalog.edge_labels.length > 0 ? (
              <div className="mt-2 border-t border-[color:var(--border-hairline)] px-3 py-3">
                <p className="pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">{t("sme.graphEdges")}</p>
                <ul className="grid gap-1">
                  {catalog.edge_labels.map((row) => (
                    <li key={row.label} className="flex items-baseline justify-between gap-2 text-xs text-[color:var(--text-body)]">
                      <span className="truncate">{row.label}</span>
                      <span className="text-[color:var(--text-muted)]">{row.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </aside>
          <section className="flex min-h-0 flex-col border-b border-[color:var(--border-hairline)] lg:border-b-0 lg:border-r">
            <div className="shrink-0 border-b border-[color:var(--border-hairline)] p-3">
              <input className="w-full rounded-lg border bg-white px-3 py-2 text-sm text-db-ink-950 caret-db-ink-950 placeholder:text-[color:var(--text-muted)]" value={query} placeholder={t("sme.graphSearch")} aria-label={t("sme.graphSearch")} onChange={(event) => setQuery(event.target.value)} />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {loading && nodes.length === 0 ? <p className="px-3 py-4 text-sm text-[color:var(--text-muted)]">{t("sme.graphLoading")}</p> : null}
              {!loading && label && nodes.length === 0 ? <p className="px-3 py-4 text-sm text-[color:var(--text-muted)]">{t("sme.graphEmptyNodes")}</p> : null}
              <ul>
                {nodes.map((node) => (
                  <li key={node.id}>
                    <button type="button" aria-pressed={selectedId === node.id} className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left ${selectedId === node.id ? "bg-db-ink-100" : "hover:bg-db-ink-50"}`} onClick={() => setSelectedId(node.id)}>
                      <span className="truncate text-sm font-medium">{node.key}</span>
                      <span className="line-clamp-2 text-xs text-[color:var(--text-muted)]">{node.preview}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {cursor != null ? <div className="p-3"><AdminButton variant="secondary" size="sm" disabled={loadingMore} onClick={() => { void more().catch(() => setError(t("sme.graphLoadError"))) }}>{t("sme.graphMore")}</AdminButton></div> : null}
            </div>
          </section>
          <aside className="min-h-0 overflow-y-auto p-4">
            {detail ? <GraphDetail detail={detail} locale={intl} outgoing={outgoing} incoming={incoming} onOpen={setSelectedId} /> : <p className="text-sm text-[color:var(--text-muted)]">{t("sme.graphSelectNode")}</p>}
          </aside>
        </div>
      </div>
    </div>
  )
}

function GraphDetail({
  detail, locale, outgoing, incoming, onOpen,
}: {
  detail: OvergraphNodeDetail
  locale: string
  outgoing: OvergraphEdge[]
  incoming: OvergraphEdge[]
  onOpen: (nodeId: number) => void
}) {
  const { t } = useLocale()
  const created = formatWhen(detail.created_at, locale)
  return (
    <div className="grid gap-4">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">{t("sme.graphKey")}</p>
        <h3 className="break-all text-sm font-medium">{detail.key}</h3>
        <p className="mt-1 text-xs text-[color:var(--text-muted)]">{detail.labels.join(" · ")}</p>
        <p className="mt-1 text-xs text-[color:var(--text-muted)]">{t("sme.graphId")} {detail.id} · {t("sme.graphWeight")} {detail.weight}{created ? ` · ${created}` : ""}</p>
      </div>
      <div>
        <p className="pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">{t("sme.graphProps")}</p>
        {Object.keys(detail.props).length === 0 ? <p className="text-sm text-[color:var(--text-muted)]">{t("sme.graphNoProps")}</p> : (
          <dl className="grid gap-2">
            {Object.entries(detail.props).map(([key, value]) => (
              <div key={key}>
                <dt className="text-xs font-medium text-[color:var(--text-muted)]">{key}</dt>
                <dd className="whitespace-pre-wrap break-words text-sm">{formatProp(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <EdgeList title={t("sme.graphOutgoing")} edges={outgoing} locale={locale} onOpen={onOpen} />
      <EdgeList title={t("sme.graphIncoming")} edges={incoming} locale={locale} onOpen={onOpen} />
    </div>
  )
}

function EdgeList({
  title, edges, locale, onOpen,
}: {
  title: string
  edges: OvergraphEdge[]
  locale: string
  onOpen: (nodeId: number) => void
}) {
  const { t } = useLocale()
  return (
    <div>
      <p className="pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">{title}</p>
      {edges.length === 0 ? <p className="text-sm text-[color:var(--text-muted)]">{t("sme.graphNoEdges")}</p> : (
        <ul className="grid gap-1">
          {edges.map((edge) => {
            const from = formatWhen(edge.valid_from, locale)
            const to = formatWhen(edge.valid_to, locale)
            return (
              <li key={edge.edge_id}>
                <button type="button" className="w-full rounded-lg border border-[color:var(--border-hairline)] px-2 py-2 text-left hover:bg-db-ink-50" disabled={edge.node == null} onClick={() => { if (edge.node) onOpen(edge.node.id) }}>
                  <span className="block text-xs font-medium text-db-gold-700">{edge.label}</span>
                  <span className="block truncate text-sm">{edge.node?.key ?? t("sme.graphMissingNode")}</span>
                  <span className="block truncate text-xs text-[color:var(--text-muted)]">{edge.node?.preview}</span>
                  {from ? <span className="block text-[10px] text-[color:var(--text-muted)]">{from}{to ? ` – ${to}` : ""}</span> : null}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
