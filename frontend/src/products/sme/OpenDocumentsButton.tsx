import { useId, useState } from "react"
import { Files } from "lucide-react"
import type { Workspace, WorkspaceArtifact } from "@/api/voiceWorkspaces"
import type { UnderlagFile } from "@/api/underlag"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale, type MessageKey } from "@/i18n"

const kindLabels = {
  underlag: "voiceWorkspaceChat.catalog.sources",
  document: "voiceWorkspaceChat.document",
  comparison: "voiceWorkspaceChat.comparison",
  relations: "voiceWorkspaceChat.relations",
  chart: "voiceWorkspaceChat.catalog.charts",
} as const satisfies Record<string, MessageKey>

type CatalogRow = {
  key: string
  name: string
  kind: string
  created: string
  disabled: boolean
  open: () => void
}

function createdStamp(value: string | null | undefined): string {
  return value ?? ""
}

function catalogRows(sources: UnderlagFile[], artifacts: WorkspaceArtifact[], onOpenSource: (id: string) => void, onOpenArtifact: (id: string) => void): CatalogRow[] {
  const rows: CatalogRow[] = [
    ...sources.map((source) => ({
      key: `source:${source.id}`,
      name: source.filename,
      kind: source.kind,
      created: createdStamp(source.created_at),
      disabled: false,
      open: () => onOpenSource(source.id),
    })),
    ...artifacts.map((artifact) => ({
      key: `artifact:${artifact.id}`,
      name: artifact.title,
      kind: artifact.kind,
      created: createdStamp(artifact.created_at),
      disabled: artifact.status !== "ready",
      open: () => onOpenArtifact(artifact.id),
    })),
  ]
  return rows.sort((left, right) => right.created.localeCompare(left.created) || left.name.localeCompare(right.name, "sv"))
}

function formatCreated(value: string, intl: string): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(intl, value.includes("T") ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(date)
}

export function OpenDocumentsCatalog({
  workspace,
  onOpenSource,
  onOpenArtifact,
}: {
  workspace: Workspace
  onOpenSource: (sourceId: string) => void
  onOpenArtifact: (artifactId: string) => void
}) {
  const { t, intl } = useLocale()
  const headingId = useId()
  const rows = catalogRows(workspace.sources, workspace.artifacts, onOpenSource, onOpenArtifact)
  return <table aria-labelledby={headingId} className="w-full border-collapse text-left text-sm">
    <caption id={headingId} className="sr-only">{t("voiceWorkspaceChat.openDocuments")}</caption>
    <thead>
      <tr className="border-b border-[color:var(--border-hairline)]">
        <th scope="col" className="sticky top-0 bg-popover px-2 py-1.5 font-medium">{t("voiceWorkspaceChat.catalog.name")}</th>
        <th scope="col" className="sticky top-0 bg-popover px-2 py-1.5 font-medium">{t("voiceWorkspaceChat.catalog.kind")}</th>
        <th scope="col" className="sticky top-0 bg-popover px-2 py-1.5 font-medium">{t("voiceWorkspaceChat.catalog.created")}</th>
      </tr>
    </thead>
    <tbody>
      {rows.map((row) => <tr key={row.key} className="border-b border-[color:var(--border-hairline)]">
        <td className="px-2 py-2"><button type="button" className="text-left font-medium hover:underline disabled:no-underline disabled:opacity-50" disabled={row.disabled} onClick={row.open}>{row.name}</button></td>
        <td className="px-2 py-2 whitespace-nowrap">{row.kind in kindLabels ? t(kindLabels[row.kind as keyof typeof kindLabels]) : row.kind}</td>
        <td className="px-2 py-2 whitespace-nowrap text-muted-foreground">{formatCreated(row.created, intl)}</td>
      </tr>)}
    </tbody>
  </table>
}

export function OpenDocumentsButton({
  workspace,
  onOpenSource,
  onOpenArtifact,
}: {
  workspace: Workspace
  onOpenSource: (sourceId: string) => void
  onOpenArtifact: (artifactId: string) => void
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const empty = workspace.sources.length === 0 && workspace.artifacts.length === 0

  return <>
    <button type="button" className="grid size-9 shrink-0 place-items-center rounded-lg border" aria-label={t("voiceWorkspaceChat.openDocuments")} onClick={() => setOpen(true)}>
      <Files size={16} />
    </button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="theme-admin flex max-h-[min(85vh,900px)] w-full flex-col gap-3 overflow-hidden sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{t("voiceWorkspaceChat.openDocuments")}</DialogTitle>
        </DialogHeader>
        {empty ? <p className="text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyDocuments")}</p> : <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <OpenDocumentsCatalog workspace={workspace} onOpenSource={(sourceId) => { setOpen(false); onOpenSource(sourceId) }} onOpenArtifact={(artifactId) => { setOpen(false); onOpenArtifact(artifactId) }} />
        </div>}
      </DialogContent>
    </Dialog>
  </>
}
