import { useEffect, useRef, useState } from "react"
import { Building2, Plus } from "lucide-react"
import { listKunder, type Kund } from "@/api/kunder"
import { createClientWorkspace, listWorkspaces, type Workspace } from "@/api/workspaces"
import type { VoiceWorkspaceParent } from "@/api/voiceWorkspaces"
import { useAuth } from "@/auth/AuthProvider"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export type SmeWorkspaceParent = VoiceWorkspaceParent & { workspace: Workspace }

export function SmeWorkspaceSelector({ parent, onChange, beforeChange }: {
  parent: SmeWorkspaceParent | null
  onChange: (parent: SmeWorkspaceParent | null) => void
  beforeChange: () => Promise<void>
}) {
  const { user, isAdmin } = useAuth()
  const { t } = useLocale()
  const requiresCustomer = isAdmin && user?.kundId == null
  const [customers, setCustomers] = useState<Kund[]>([])
  const [customerId, setCustomerId] = useState<number | undefined>()
  const [rows, setRows] = useState<Workspace[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const latest = useRef({ onChange, beforeChange, t })
  latest.current = { onChange, beforeChange, t }
  const generation = useRef(0)

  useEffect(() => {
    if (!requiresCustomer) return
    let cancelled = false
    void listKunder().then((result) => { if (!cancelled) setCustomers(result) }).catch((caught: unknown) => { if (!cancelled) setError(workspaceErrorMessage(caught, latest.current.t, "workspaceChat.loadError")) })
    return () => { cancelled = true }
  }, [requiresCustomer])

  useEffect(() => {
    const epoch = ++generation.current
    let cancelled = false
    setRows([]); setError(null)
    latest.current.onChange(null)
    if (requiresCustomer && customerId == null) return
    setBusy(true)
    void listWorkspaces(customerId).then((result) => {
      if (cancelled || epoch !== generation.current) return
      setRows(result)
      const company = result.find((row) => row.kind === "company")
      if (company) latest.current.onChange({ workspaceId: company.id, customerId, workspace: company })
    }).catch((caught: unknown) => { if (!cancelled) setError(workspaceErrorMessage(caught, latest.current.t, "workspaceChat.loadError")) }).finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [customerId, requiresCustomer])

  async function choose(workspaceId: string, nextCustomerId = customerId) {
    setBusy(true); setError(null)
    try { await latest.current.beforeChange(); const workspace = rows.find((row) => row.id === workspaceId); latest.current.onChange(workspace ? { workspaceId, customerId: nextCustomerId, workspace } : null); return true }
    catch (caught) { setError(workspaceErrorMessage(caught, t, "workspaceChat.actionError")) }
    finally { setBusy(false) }
  }

  async function create() {
    if (!name.trim() || busy || !parent) return
    const epoch = generation.current
    setBusy(true); setError(null)
    try {
      const created = await createClientWorkspace(name.trim(), customerId)
      if (epoch !== generation.current) return
      await latest.current.beforeChange()
      setRows((previous) => [...previous, created]); latest.current.onChange({ workspaceId: created.id, customerId, workspace: created }); setOpen(false)
    } catch (caught) { setError(workspaceErrorMessage(caught, t, "workspaceChat.actionError")) }
    finally { setBusy(false) }
  }

  return <>
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-white px-4 py-2">
      {requiresCustomer ? <select className="w-full min-w-0 rounded border bg-white px-2 py-2 text-sm sm:w-auto sm:max-w-48" aria-label={t("workspaceChat.organization")} value={customerId ?? ""} disabled={busy} onChange={(event) => {
        const next = event.target.value ? Number(event.target.value) : undefined
        void choose("", next).then((changed) => { if (changed) setCustomerId(next) })
      }}><option value="">{t("workspaceChat.chooseOrganization")}</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select> : null}
      <Building2 size={18} className="shrink-0 text-db-gold-600" aria-hidden="true" />
      <select className="min-w-0 flex-1 rounded border bg-white px-3 py-2 text-sm sm:max-w-80" aria-label={t("workspaceChat.workspace")} value={parent?.workspaceId ?? ""} disabled={busy || !rows.length} onChange={(event) => { void choose(event.target.value) }}><option value="" disabled>{t("workspaceChat.workspace")}</option>{rows.map((row) => <option key={row.id} value={row.id}>{row.name}{row.kind === "company" ? ` · ${t("workspaceChat.company")}` : ""}</option>)}</select>
      <AdminButton variant="secondary" size="sm" disabled={busy || !parent} aria-label={t("workspaceChat.newWorkspace")} onClick={() => { setName(""); setOpen(true) }}><Plus size={16} aria-hidden="true" /><span className="hidden sm:inline">{t("workspaceChat.newWorkspace")}</span></AdminButton>
      <span className="hidden min-w-0 truncate text-xs text-muted-foreground lg:block">{parent ? t(rows.find((row) => row.id === parent.workspaceId)?.kind === "client" ? "workspaceChat.clientIntro" : "workspaceChat.companyIntro") : null}</span>
      {error ? <span role="alert" className="w-full text-sm text-destructive">{error}</span> : null}
    </div>
    <Dialog open={open} onOpenChange={(value) => { if (!busy) setOpen(value) }}><DialogContent className="theme-admin max-w-md"><form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); void create() }}><DialogHeader><DialogTitle>{t("workspaceChat.newWorkspace")}</DialogTitle><DialogDescription>{t("workspaceChat.workspaceIntro")}</DialogDescription></DialogHeader><label className="grid gap-2 text-sm">{t("workspaceChat.workspaceName")}<input autoFocus required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} className="rounded border bg-white p-3" /></label>{error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}<DialogFooter><AdminButton type="button" variant="secondary" disabled={busy} onClick={() => setOpen(false)}>{t("workspaceChat.cancel")}</AdminButton><AdminButton type="submit" disabled={busy || !name.trim()}>{t("workspaceChat.create")}</AdminButton></DialogFooter></form></DialogContent></Dialog>
  </>
}
