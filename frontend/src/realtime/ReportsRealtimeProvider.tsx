import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import type { Report } from "@/api/reports"
import { connectJsonWebSocket, type WsStatus } from "@/lib/ws"

type ReportsRealtimeValue = {
  reports: Report[]
  activeCount: number
  connected: boolean
  status: WsStatus
  error: string | null
}

const ReportsRealtimeContext = createContext<ReportsRealtimeValue | null>(null)

function isReport(value: unknown): value is Report {
  if (!value || typeof value !== "object") return false
  const r = value as Record<string, unknown>
  return typeof r.id === "string" && typeof r.status === "string"
}

function upsertReport(list: Report[], report: Report): Report[] {
  const idx = list.findIndex((r) => r.id === report.id)
  if (idx === -1) return [report, ...list].slice(0, 50)
  const next = list.slice()
  next[idx] = report
  next.sort((a, b) => {
    const ta = new Date(a.created_at).getTime()
    const tb = new Date(b.created_at).getTime()
    return tb - ta
  })
  return next.slice(0, 50)
}

function removeReports(list: Report[], ids: string[]): Report[] {
  if (ids.length === 0) return list
  const gone = new Set(ids)
  return list.filter((r) => !gone.has(r.id))
}

export function ReportsRealtimeProvider({ children }: { children: ReactNode }) {
  const [reports, setReports] = useState<Report[]>([])
  const [status, setStatus] = useState<WsStatus>("connecting")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const conn = connectJsonWebSocket({
      path: "/ws/reports",
      onStatus: setStatus,
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const msg = data as Record<string, unknown>
        if (msg.type === "reports.snapshot" && Array.isArray(msg.reports)) {
          setReports(msg.reports.filter(isReport))
          setError(null)
          return
        }
        if (msg.type === "report.updated" && isReport(msg.report)) {
          setReports((prev) => upsertReport(prev, msg.report as Report))
          setError(null)
          return
        }
        if (msg.type === "report.deleted" && Array.isArray(msg.ids)) {
          const ids = msg.ids.filter((id): id is string => typeof id === "string")
          setReports((prev) => removeReports(prev, ids))
          setError(null)
        }
      },
    })
    const ping = window.setInterval(() => {
      conn.send({ type: "ping" })
    }, 25_000)
    return () => {
      window.clearInterval(ping)
      conn.close()
    }
  }, [])

  const value = useMemo<ReportsRealtimeValue>(() => {
    const activeCount = reports.filter(
      (r) => r.status === "pending" || r.status === "running",
    ).length
    return {
      reports,
      activeCount,
      connected: status === "open",
      status,
      error,
    }
  }, [reports, status, error])

  return (
    <ReportsRealtimeContext.Provider value={value}>{children}</ReportsRealtimeContext.Provider>
  )
}

export function useReportsRealtime(): ReportsRealtimeValue {
  const ctx = useContext(ReportsRealtimeContext)
  if (!ctx) {
    throw new Error("useReportsRealtime must be used within ReportsRealtimeProvider")
  }
  return ctx
}
