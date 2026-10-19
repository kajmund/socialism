import { ProfileForm } from "@/components/profiles/ProfileForm"
import { AdminButton } from "@/components/ui/admin-button"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { useEffect, useMemo, useState } from "react"
import { createPortal } from "react-dom"
import { listModules, type ProductModule } from "@/api/modules"
import {
  deleteKundDocuments,
  getKundDocuments,
  listKunder,
  updateKundModules,
  updateKundProduct,
  type Kund,
  type KundDocumentCounts,
  type KundDocumentSummary,
} from "@/api/kunder"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"
import { useAuth } from "@/auth/AuthProvider"

const DOCUMENT_COUNT_FIELDS: { key: keyof KundDocumentCounts; labelKey: MessageKey }[] = [
  { key: "files", labelKey: "tools.kunder.documentCountFiles" },
  { key: "knowledge_documents", labelKey: "tools.kunder.documentCountKnowledgeDocuments" },
  { key: "canonical_documents", labelKey: "tools.kunder.documentCountCanonicalDocuments" },
  { key: "text_units", labelKey: "tools.kunder.documentCountTextUnits" },
  { key: "document_knowledge_items", labelKey: "tools.kunder.documentCountKnowledgeItems" },
  { key: "claims", labelKey: "tools.kunder.documentCountClaims" },
  { key: "entities", labelKey: "tools.kunder.documentCountEntities" },
  { key: "relationships", labelKey: "tools.kunder.documentCountRelationships" },
  { key: "graph_events", labelKey: "tools.kunder.documentCountGraphEvents" },
  { key: "graph_facts", labelKey: "tools.kunder.documentCountGraphFacts" },
  { key: "graph_nodes", labelKey: "tools.kunder.documentCountGraphNodes" },
  { key: "ingest_batches", labelKey: "tools.kunder.documentCountIngestBatches" },
]

export function KunderPage() {
  const { t, intl } = useLocale()
  const { refreshProfile } = useAuth()
  const [kunder, setKunder] = useState<Kund[]>([])
  const [modules, setModules] = useState<ProductModule[]>([])
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [documentsTarget, setDocumentsTarget] = useState<Kund | null>(null)
  const [documentsSummary, setDocumentsSummary] = useState<KundDocumentSummary | null>(null)
  const [documentsLoading, setDocumentsLoading] = useState(false)
  const [documentsError, setDocumentsError] = useState<string | null>(null)
  const [confirmSlug, setConfirmSlug] = useState("")
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([listKunder(), listModules()])
      .then(([kundRows, moduleRows]) => {
        if (cancelled) return
        setKunder(kundRows)
        setModules(moduleRows)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("tools.kunder.loadError"))
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

  useEffect(() => {
    if (!documentsTarget) return
    let cancelled = false
    setDocumentsLoading(true)
    setDocumentsSummary(null)
    setDocumentsError(null)
    getKundDocuments(documentsTarget.id)
      .then((summary) => {
        if (cancelled) return
        setDocumentsSummary(summary)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setDocumentsError(
          err instanceof ApiError ? err.message : t("tools.kunder.documentsLoadError"),
        )
      })
      .finally(() => {
        if (!cancelled) setDocumentsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [documentsTarget, t])

  const knownIds = useMemo(() => modules.map((row) => row.id), [modules])
  const documentCounts = documentsSummary?.counts
  const documentCountRows = documentCounts
    ? DOCUMENT_COUNT_FIELDS.filter((field) => documentCounts[field.key] > 0)
    : []

  function moduleLabel(id: string): string {
    const manifest = MODULE_REGISTRY[id]
    if (manifest) return t(manifest.nameKey)
    return modules.find((row) => row.id === id)?.name ?? id
  }

  async function toggleModule(kund: Kund, moduleId: string, enabled: boolean) {
    const next = enabled
      ? [...kund.available_modules.filter((id) => id !== moduleId), moduleId]
      : kund.available_modules.filter((id) => id !== moduleId)
    setSavingId(kund.id)
    setError(null)
    try {
      const updated = await updateKundModules(kund.id, next)
      setKunder((prev) => prev.map((row) => (row.id === updated.id ? updated : row)))
      await refreshProfile()
      setToast(t("tools.kunder.saved"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  async function changeProduct(kund: Kund, product: string | null) {
    setSavingId(kund.id)
    setError(null)
    try {
      const updated = await updateKundProduct(kund.id, product)
      setKunder((prev) => prev.map((row) => (row.id === updated.id ? updated : row)))
      setToast(t("tools.kunder.productSaved"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSavingId(null)
    }
  }

  function blockedReasonText(reason: string | null): string | null {
    switch (reason) {
      case "document_ingest_active":
        return t("tools.kunder.blockedDocumentIngest")
      case "graph_ingest_active":
        return t("tools.kunder.blockedGraphIngest")
      default:
        return null
    }
  }

  function openDocuments(kund: Kund) {
    setDocumentsTarget(kund)
    setConfirmSlug("")
  }

  function closeDocuments() {
    if (deleting) return
    setDocumentsTarget(null)
    setDocumentsSummary(null)
    setDocumentsError(null)
    setConfirmSlug("")
  }

  async function onDeleteDocuments() {
    if (!documentsTarget || !documentsSummary) return
    setDeleting(true)
    setDocumentsError(null)
    try {
      const result = await deleteKundDocuments(documentsTarget.id, documentsSummary.kund_slug)
      setDocumentsTarget(null)
      setDocumentsSummary(null)
      setConfirmSlug("")
      setToast(
        t("tools.kunder.documentsDeleted", {
          files: result.deleted.files,
          vectorDocuments: result.vector_documents,
          storedObjects: result.stored_objects,
        }),
      )
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setDocumentsError(blockedReasonText(err.message) ?? err.message)
      } else {
        setDocumentsError(t("tools.kunder.documentsDeleteError"))
      }
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="muted">{t("tools.kunder.intro")}</p>
      {toast ? <p className="text-sm text-muted-foreground">{toast}</p> : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="muted">{t("tools.kunder.loading")}</p> : null}
      {!loading && kunder.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("tools.kunder.empty")}</p>
      ) : null}
      {!loading && kunder.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border-hairline)]">
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colName")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colSlug")}</th>
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colProduct")}</th>
                {knownIds.map((id) => (
                  <th key={id} className="px-2 py-1.5 font-medium">
                    {moduleLabel(id)}
                  </th>
                ))}
                <th className="px-2 py-1.5 font-medium">{t("tools.kunder.colActions")}</th>
              </tr>
            </thead>
            <tbody>
              {kunder.map((kund) => (
                <tr key={kund.id} className="border-b border-[color:var(--border-hairline)]">
                  <td className="px-2 py-2">{kund.name}<details><summary>{t("profile.organization")}</summary><ProfileForm organization values={kund} onSave={async (changes) => { const updated = await api.patch<Kund>(`/kunder/${kund.id}`, changes); setKunder((rows) => rows.map((row) => row.id === updated.id ? updated : row)) }} /></details></td>
                  <td className="px-2 py-2 font-mono text-xs">{kund.slug}</td>
                  <td className="px-2 py-2">
                    <select
                      className="h-8 rounded-md border border-[color:var(--border-hairline)] bg-transparent px-2 text-sm"
                      value={kund.product ?? ""}
                      disabled={savingId === kund.id}
                      aria-label={t("tools.kunder.productAria", { kund: kund.name })}
                      onChange={(event) => {
                        void changeProduct(kund, event.target.value || null)
                      }}
                    >
                      <option value="">{t("tools.kunder.noProduct")}</option>
                      <option value="sme">{t("tools.kunder.productSme")}</option>
                    </select>
                  </td>
                  {knownIds.map((id) => {
                    const checked = kund.available_modules.includes(id)
                    return (
                      <td key={id} className="px-2 py-2">
                        <label className="inline-flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={savingId === kund.id}
                            aria-label={t("tools.kunder.toggleAria", {
                              kund: kund.name,
                              module: moduleLabel(id),
                            })}
                            onChange={(event) => {
                              void toggleModule(kund, id, event.target.checked)
                            }}
                          />
                        </label>
                      </td>
                    )
                  })}
                  <td className="px-2 py-2">
                    <AdminButton
                      variant="secondary"
                      size="sm"
                      aria-label={t("tools.kunder.documentsActionAria", { kund: kund.name })}
                      onClick={() => openDocuments(kund)}
                    >
                      {t("tools.kunder.documentsAction")}
                    </AdminButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {savingId != null ? (
        <p className="text-sm text-muted-foreground">{t("common.saving")}</p>
      ) : null}

      {documentsTarget
        ? createPortal(
            <div
              className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
              role="dialog"
              aria-modal="true"
              aria-labelledby="purge-documents-title"
              onClick={(event) => {
                if (event.target === event.currentTarget) closeDocuments()
              }}
            >
              <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 p-5 shadow-xl">
                <h2
                  id="purge-documents-title"
                  className="mb-4 text-lg font-medium text-foreground"
                >
                  {t("tools.kunder.documentsTitle", { kund: documentsTarget.name })}
                </h2>

                {documentsLoading ? (
                  <p className="muted">{t("tools.kunder.documentsLoading")}</p>
                ) : null}

                {documentsSummary ? (
                  <div className="flex flex-col gap-4">
                    {documentCountRows.length > 0 ? (
                      <div>
                        <h3 className="mb-1 text-sm font-medium">
                          {t("tools.kunder.documentsCountsTitle")}
                        </h3>
                        <ul className="list-inside list-disc text-sm text-muted-foreground">
                          {documentCountRows.map((field) => (
                            <li key={field.key}>
                              {t(field.labelKey)}:{" "}
                              <span className="font-mono">
                                {new Intl.NumberFormat(intl).format(
                                  documentsSummary.counts[field.key],
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        {t("tools.kunder.documentsEmpty")}
                      </p>
                    )}

                    <p className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                      {t("tools.kunder.documentsIrreversible")}
                    </p>

                    {documentsSummary.blocked_reason ? (
                      <p className="text-sm text-destructive" role="alert">
                        {blockedReasonText(documentsSummary.blocked_reason)}
                      </p>
                    ) : null}

                    <label className="flex flex-col gap-1 text-sm">
                      <span>
                        {t("tools.kunder.documentsConfirmLabel", {
                          slug: documentsSummary.kund_slug,
                        })}
                      </span>
                      <input
                        type="text"
                        value={confirmSlug}
                        autoComplete="off"
                        spellCheck={false}
                        disabled={deleting || documentsSummary.blocked_reason !== null}
                        placeholder={t("tools.kunder.documentsConfirmPlaceholder")}
                        onChange={(event) => setConfirmSlug(event.target.value)}
                        className="h-10 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 font-mono disabled:opacity-50"
                      />
                      {confirmSlug.length > 0 &&
                      confirmSlug !== documentsSummary.kund_slug ? (
                        <span className="text-xs text-destructive">
                          {t("tools.kunder.documentsConfirmMismatch")}
                        </span>
                      ) : null}
                    </label>
                  </div>
                ) : null}

                {!documentsLoading && documentsError ? (
                  <p className="mt-4 text-sm text-destructive" role="alert">
                    {documentsError}
                  </p>
                ) : null}

                <div className="mt-4 flex justify-end gap-2">
                  <AdminButton variant="secondary" size="md" disabled={deleting} onClick={closeDocuments}>
                    {t("common.cancel")}
                  </AdminButton>
                  {documentsSummary ? (
                    <Button
                      type="button"
                      variant="destructive"
                      size="lg"
                      disabled={
                        deleting ||
                        documentsSummary.blocked_reason !== null ||
                        confirmSlug !== documentsSummary.kund_slug
                      }
                      onClick={() => void onDeleteDocuments()}
                    >
                      {deleting
                        ? t("tools.kunder.documentsDeleting")
                        : t("tools.kunder.documentsDeleteSubmit")}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
