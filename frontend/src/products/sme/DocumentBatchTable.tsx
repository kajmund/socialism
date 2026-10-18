import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { DocumentBatchBar } from "./DocumentBatchBar"
import type { LocalBatchRow } from "./documentBatch"
import { rowIngestPercent, rowUploadPercent, stageKey } from "./documentBatch"

export function DocumentBatchTable({
  rows,
  onOpen,
  onRetry,
}: {
  rows: LocalBatchRow[]
  onOpen: (sourceId: string) => void
  onRetry: (row: LocalBatchRow) => void
}) {
  const { t } = useLocale()
  return (
    <div className="h-full min-h-0 overflow-auto rounded-xl border">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="sticky top-0 bg-db-ink-50">
          <tr>
            <th className="p-3 font-medium">{t("documentBatch.document")}</th>
            <th className="w-40 p-3 font-medium">{t("documentBatch.upload")}</th>
            <th className="w-40 p-3 font-medium">{t("documentBatch.ingest")}</th>
            <th className="w-48 p-3 font-medium">{t("documentBatch.status")}</th>
          </tr>
        </thead>
        <tbody>
          {!rows.length ? (
            <tr>
              <td colSpan={4} className="p-6 text-sm text-muted-foreground">{t("documentBatch.empty")}</td>
            </tr>
          ) : null}
          {rows.map((row) => (
            <tr key={row.clientKey} className="border-t">
              <td className="max-w-0 p-3">
                <span className="block truncate font-medium">{row.filename}</span>
                {row.item?.searchable ? <span className="text-xs text-muted-foreground">{t("documentBatch.searchable")}</span> : null}
                {row.item?.error ? <span className="block text-xs text-destructive">{row.item.error}</span> : null}
              </td>
              <td className="p-3"><DocumentBatchBar value={rowUploadPercent(row)} /></td>
              <td className="p-3"><DocumentBatchBar value={rowIngestPercent(row)} /></td>
              <td className="p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span>{t(stageKey(row.item?.stage ?? (row.uploadLocal > 0 ? "uploading" : "waiting")))}</span>
                  {row.item?.searchable && row.item.stored_object_id ? (
                    <AdminButton type="button" size="sm" variant="secondary" onClick={() => onOpen(row.item!.stored_object_id!)}>
                      {t("documentBatch.open")}
                    </AdminButton>
                  ) : null}
                  {row.item?.status === "failed" ? (
                    <AdminButton type="button" size="sm" variant="secondary" onClick={() => onRetry(row)}>
                      {t("documentBatch.retry")}
                    </AdminButton>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
