import { useParams } from "react-router-dom"
import { AdminShell } from "@/components/layout/AdminShell"
import { ResearchMonitorPanel } from "@/components/research/ResearchMonitorPanel"
import { useLocale } from "@/i18n"

export function ResearchMonitorPage() {
  const { attemptId } = useParams<{ attemptId: string }>()
  const { t } = useLocale()
  return (
    <AdminShell>
      <div className="wrap admin-page">
        <div className="admin-page-chrome">
          <div className="crumb">{t("execution.researchMonitor.crumb")}</div>
          <div>
            <h1>{t("execution.researchMonitor.title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("execution.researchMonitor.intro")}</p>
          </div>
        </div>
        <div className="admin-page-body py-5">
          {attemptId ? <ResearchMonitorPanel attemptId={attemptId} /> : <div className="empty-state">{t("execution.page.notFound")}</div>}
        </div>
      </div>
    </AdminShell>
  )
}
