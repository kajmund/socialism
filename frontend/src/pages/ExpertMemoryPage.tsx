import { useCallback, useEffect, useMemo, useState } from "react"
import {
  clearExpertMemories,
  deleteExpertMemory,
  listExpertMemories,
  updateExpertMemory,
  type ExpertMemory,
  type ExpertMemoryExpert,
} from "@/api/expertMemory"
import { listKunder, type Kund } from "@/api/kunder"
import { ExpertMemoryLog } from "@/components/experts/ExpertMemoryLog"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function ExpertMemoryPage() {
  const { t, intl } = useLocale()
  const [kunder, setKunder] = useState<Kund[]>([])
  const [experts, setExperts] = useState<ExpertMemoryExpert[]>([])
  const [memories, setMemories] = useState<ExpertMemory[]>([])
  const [customerId, setCustomerId] = useState("")
  const [expertId, setExpertId] = useState("")
  const [loading, setLoading] = useState(true)
  const [clearing, setClearing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const formatWhen = useCallback(
    (iso: string) => {
      if (!iso) return ""
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return iso
      return new Intl.DateTimeFormat(intl, {
        dateStyle: "short",
        timeStyle: "short",
      }).format(d)
    },
    [intl],
  )

  const kundName = useCallback(
    (id: number | null) => kunder.find((row) => row.id === id)?.name ?? "",
    [kunder],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const kundId = customerId ? Number(customerId) : undefined
      const [kundRows, listed] = await Promise.all([
        listKunder(),
        listExpertMemories({
          customer_id: kundId,
          expert_id: expertId || undefined,
        }),
      ])
      setKunder(kundRows)
      setExperts(listed.experts ?? [])
      setMemories(listed.memories)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.memory.loadError"))
    } finally {
      setLoading(false)
    }
  }, [customerId, expertId, t])

  useEffect(() => {
    void load()
  }, [load])

  const expertOptions = useMemo(() => {
    const byId = new Map<string, string>()
    for (const expert of experts) {
      if (customerId && String(expert.customer_id) !== customerId) continue
      byId.set(expert.expert_id, expert.name || expert.expert_id)
    }
    for (const row of memories) {
      if (row.expert_id && !byId.has(row.expert_id)) {
        byId.set(row.expert_id, row.expert_name || row.expert_id)
      }
    }
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1], intl))
  }, [customerId, experts, memories, intl])

  const confirmClearText = useMemo(() => {
    const kund = customerId
      ? kunder.find((row) => String(row.id) === customerId)?.name
      : ""
    const expert = expertId
      ? expertOptions.find(([id]) => id === expertId)?.[1]
      : ""
    if (kund && expert) return t("tools.memory.confirmClearBoth", { customer: kund, expert })
    if (kund) return t("tools.memory.confirmClearCustomer", { customer: kund })
    if (expert) return t("tools.memory.confirmClearExpert", { expert })
    return t("tools.memory.confirmClearAll")
  }, [customerId, expertId, expertOptions, kunder, t])

  async function onClear() {
    setClearing(true)
    setError(null)
    try {
      await clearExpertMemories({
        customer_id: customerId ? Number(customerId) : undefined,
        expert_id: expertId || undefined,
      })
      setConfirmClear(false)
      setMemories([])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("tools.memory.clearError"))
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium">{t("tools.memory.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("tools.memory.intro")}</p>
          {!loading ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("tools.memory.meta", { count: String(memories.length) })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={loading || clearing} onClick={() => void load()}>
            {t("tools.memory.refresh")}
          </Button>
          {!confirmClear ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={loading || clearing || memories.length === 0}
              onClick={() => setConfirmClear(true)}
            >
              {t("tools.memory.clear")}
            </Button>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="max-w-[22rem] text-xs text-muted-foreground">{confirmClearText}</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={clearing}
                onClick={() => setConfirmClear(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={clearing}
                onClick={() => void onClear()}
              >
                {clearing ? t("tools.memory.clearing") : t("tools.memory.clearConfirm")}
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-[180px] flex-col gap-1 text-sm">
          <span className="text-muted-foreground">{t("tools.memory.customerLabel")}</span>
          <select
            className="rounded-md border border-[color:var(--border-hairline)] bg-background px-2 py-1.5"
            value={customerId}
            onChange={(e) => {
              setCustomerId(e.target.value)
              setExpertId("")
              setConfirmClear(false)
            }}
          >
            <option value="">{t("tools.memory.allCustomers")}</option>
            {kunder.map((kund) => (
              <option key={kund.id} value={kund.id}>
                {kund.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[180px] flex-col gap-1 text-sm">
          <span className="text-muted-foreground">{t("tools.memory.expertLabel")}</span>
          <select
            className="rounded-md border border-[color:var(--border-hairline)] bg-background px-2 py-1.5"
            value={expertId}
            onChange={(e) => {
              setExpertId(e.target.value)
              setConfirmClear(false)
            }}
          >
            <option value="">{t("tools.memory.allExperts")}</option>
            {expertOptions.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p className="muted">{t("tools.memory.loading")}</p> : null}
      {!loading ? (
        <ExpertMemoryLog
          memories={memories}
          empty={t("tools.memory.empty")}
          showExpert
          customerName={customerId ? undefined : kundName}
          formatWhen={formatWhen}
          onSave={async (row, text) => {
            const updated = await updateExpertMemory(row.id, text)
            setMemories((prev) => prev.map((item) => (item.id === row.id ? updated : item)))
            return updated
          }}
          onDelete={async (row) => {
            await deleteExpertMemory(row.id)
            setMemories((prev) => prev.filter((item) => item.id !== row.id))
          }}
        />
      ) : null}
    </div>
  )
}
