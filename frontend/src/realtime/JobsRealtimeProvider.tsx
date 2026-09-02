import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import type { Job } from "@/api/jobs"
import { useAuth } from "@/auth/AuthProvider"
import { realtimeCustomerIdForRole } from "@/lib/scoping"
import { connectJsonWebSocket, type WsStatus } from "@/lib/ws"

type JobsRealtimeValue = {
  jobs: Job[]
  activeCount: number
  connected: boolean
  status: WsStatus
  error: string | null
  applyJob: (job: Job) => void
}

const JobsRealtimeContext = createContext<JobsRealtimeValue | null>(null)

function isJob(value: unknown): value is Job {
  if (!value || typeof value !== "object") return false
  const j = value as Record<string, unknown>
  return typeof j.id === "string" && typeof j.status === "string"
}

function isArchived(job: Job): boolean {
  return Boolean(job.archived_at)
}

function upsertJob(list: Job[], job: Job): Job[] {
  if (isArchived(job)) {
    return list.filter((j) => j.id !== job.id)
  }
  const idx = list.findIndex((j) => j.id === job.id)
  if (idx === -1) return [job, ...list].slice(0, 50)
  const next = list.slice()
  next[idx] = job
  next.sort((a, b) => {
    const ta = new Date(a.created_at).getTime()
    const tb = new Date(b.created_at).getTime()
    return tb - ta
  })
  return next.slice(0, 50)
}

export function JobsRealtimeProvider({ children }: { children: ReactNode }) {
  const { role, loading } = useAuth()
  const customerId = realtimeCustomerIdForRole(role)
  const [jobs, setJobs] = useState<Job[]>([])
  const [status, setStatus] = useState<WsStatus>("connecting")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (loading) return

    setJobs([])
    setError(null)

    const conn = connectJsonWebSocket({
      path: "/ws/jobs",
      onStatus: setStatus,
      onOpen: () => {
        const hello: Record<string, unknown> = {
          type: "hello",
          scope: "jobs_watch",
        }
        if (customerId != null) {
          hello.customer_id = customerId
        }
        conn.send(hello)
      },
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const msg = data as Record<string, unknown>
        if (msg.type === "jobs.snapshot" && Array.isArray(msg.jobs)) {
          const rows = msg.jobs.filter(isJob).filter((job) => !isArchived(job))
          setJobs(rows)
          setError(null)
          return
        }
        if (msg.type === "job.updated" && isJob(msg.job)) {
          setJobs((prev) => upsertJob(prev, msg.job as Job))
          setError(null)
        }
      },
    })
    // Lightweight keepalive so proxies don't idle-close the socket.
    const ping = window.setInterval(() => {
      conn.send({ type: "ping" })
    }, 25_000)
    return () => {
      window.clearInterval(ping)
      conn.close()
    }
  }, [customerId, loading])

  const applyJob = useCallback((job: Job) => {
    setJobs((prev) => upsertJob(prev, job))
  }, [])

  const value = useMemo<JobsRealtimeValue>(() => {
    const activeCount = jobs.filter(
      (j) => j.status === "pending" || j.status === "running",
    ).length
    return {
      jobs,
      activeCount,
      connected: status === "open",
      status,
      error,
      applyJob,
    }
  }, [applyJob, jobs, status, error])

  return (
    <JobsRealtimeContext.Provider value={value}>{children}</JobsRealtimeContext.Provider>
  )
}

export function useJobsRealtime(): JobsRealtimeValue {
  const ctx = useContext(JobsRealtimeContext)
  if (!ctx) {
    throw new Error("useJobsRealtime must be used within JobsRealtimeProvider")
  }
  return ctx
}
