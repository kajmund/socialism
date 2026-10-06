import { Fragment, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Wrench } from "lucide-react"
import { AdminButton } from "@/components/ui/admin-button"
import {
  EXPERT_TOOLS,
  selectAllExpertTools,
  toggleExpertTool,
  type ExpertToolGroup,
  type ExpertToolId,
} from "@/data/expert-tools"
import { WORKSPACE_CHAT_TOOLS, type WorkspaceChatToolId } from "@/data/workspace-chat-tools"
import { useLocale, type MessageKey } from "@/i18n"

const GROUP_ORDER: ExpertToolGroup[] = [
  "company",
  "search",
  "research",
  "consult",
  "context",
]

const GROUP_LABEL: Record<ExpertToolGroup, MessageKey> = {
  company: "experts.tools.groupCompany",
  search: "experts.tools.groupSearch",
  research: "experts.tools.groupResearch",
  consult: "experts.tools.groupConsult",
  context: "profile.groupContext",
}

const WORKSPACE_TOOL_LABEL: Record<WorkspaceChatToolId, MessageKey> = {
  get_workspace_context: "experts.tools.workspace.get_workspace_context",
  ingest_source: "experts.tools.workspace.ingest_source",
  get_job_status: "experts.tools.workspace.get_job_status",
  search_knowledge: "experts.tools.workspace.search_knowledge",
  read_source: "experts.tools.workspace.read_source",
  compare_sources: "experts.tools.workspace.compare_sources",
  get_relations: "experts.tools.workspace.get_relations",
  render_chart: "experts.tools.workspace.render_chart",
  create_document: "experts.tools.workspace.create_document",
  revise_document: "experts.tools.workspace.revise_document",
  export_document: "experts.tools.workspace.export_document",
  start_research: "experts.tools.workspace.start_research",
  open_ingest_picker: "experts.tools.workspace.open_ingest_picker",
  show_evidence: "experts.tools.workspace.show_evidence",
  show_document: "experts.tools.workspace.show_document",
  focus_anchor: "experts.tools.workspace.focus_anchor",
  show_comparison: "experts.tools.workspace.show_comparison",
  show_relations: "experts.tools.workspace.show_relations",
  show_knowledge: "experts.tools.workspace.show_knowledge",
  show_artifact: "experts.tools.workspace.show_artifact",
}

const TOOL_LABEL: Record<ExpertToolId, MessageKey> = {
  search_companies: "experts.tools.search_companies",
  lookup_company: "experts.tools.lookup_company",
  validate_orgnr: "experts.tools.validate_orgnr",
  search_duckduckgo: "experts.tools.search_duckduckgo",
  search_wiki: "experts.tools.search_wiki",
  start_research: "experts.tools.start_research",
  lookup_research_evidence: "experts.tools.lookup_research_evidence",
  ask_expert: "experts.tools.ask_expert",
  get_actor_context: "profile.get_actor_context",
  propose_actor_context_update: "profile.propose_actor_context_update",
}

export type ExpertToolsFieldsProps = {
  tools: ExpertToolId[]
  onChange: (tools: ExpertToolId[]) => void
  disabled?: boolean
  error?: string | null
  titleKey?: MessageKey
  introKey?: MessageKey
  includeWorkspaceTools?: boolean
}

function ExpertToolsTable({
  tools,
  onChange,
  disabled = false,
}: ExpertToolsFieldsProps) {
  const { t } = useLocale()
  const selectAllRef = useRef<HTMLInputElement>(null)
  const selected = new Set(tools)
  const allSelected = EXPERT_TOOLS.every((tool) => selected.has(tool.id))
  const someSelected = EXPERT_TOOLS.some((tool) => selected.has(tool.id))

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected && !allSelected
    }
  }, [allSelected, someSelected])

  function setAll(checked: boolean) {
    onChange(selectAllExpertTools(checked))
  }

  function toggle(id: ExpertToolId, checked: boolean) {
    onChange(toggleExpertTool(tools, id, checked))
  }

  return (
    <table className="lt">
      <tbody>
        <tr>
          <td className="k">
            <label htmlFor="expert-tools-select-all">
              {t("experts.tools.selectAll")}
            </label>
          </td>
          <td>
            <input
              ref={selectAllRef}
              id="expert-tools-select-all"
              type="checkbox"
              checked={allSelected}
              disabled={disabled}
              onChange={(e) => setAll(e.target.checked)}
            />
          </td>
        </tr>
        {GROUP_ORDER.map((group) => (
          <Fragment key={group}>
            <tr className="lt-sub">
              <td className="k" colSpan={2}>
                {t(GROUP_LABEL[group])}
              </td>
            </tr>
            {EXPERT_TOOLS.filter((tool) => tool.group === group).map((tool) => (
              <tr key={tool.id}>
                <td className="k">
                  <label htmlFor={`expert-tool-${tool.id}`}>
                    {t(TOOL_LABEL[tool.id])}
                  </label>
                </td>
                <td>
                  <input
                    id={`expert-tool-${tool.id}`}
                    type="checkbox"
                    checked={selected.has(tool.id)}
                    disabled={disabled}
                    onChange={(e) => toggle(tool.id, e.target.checked)}
                  />
                </td>
              </tr>
            ))}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

export function ExpertToolsFields({
  tools,
  onChange,
  disabled = false,
  error = null,
  titleKey = "experts.composer.layerTools",
  introKey = "experts.tools.intro",
  includeWorkspaceTools = false,
}: ExpertToolsFieldsProps) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const overlayMouseDownRef = useRef(false)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  return (
    <>
      <button
        type="button"
        className="results-icon-btn"
        title={t("experts.tools.openAria")}
        aria-label={t("experts.tools.openAria")}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Wrench className="size-3.5" aria-hidden />
      </button>
      {open
        ? createPortal(
            <div
              className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
              role="dialog"
              aria-modal="true"
              aria-labelledby="expert-tools-title"
              onMouseDown={(e) => {
                overlayMouseDownRef.current = e.target === e.currentTarget
              }}
              onClick={(e) => {
                if (e.target === e.currentTarget && overlayMouseDownRef.current) {
                  setOpen(false)
                }
                overlayMouseDownRef.current = false
              }}
            >
              <div
                className="w-full max-w-md rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="border-b border-[color:var(--border-hairline)] px-5 py-4">
                  <h2
                    id="expert-tools-title"
                    className="text-base font-medium text-foreground"
                  >
                    {t(titleKey)}
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t(introKey)}
                  </p>
                </div>
                <div className="max-h-[70vh] overflow-auto px-5 py-4">
                  <ExpertToolsTable
                    tools={tools}
                    onChange={onChange}
                    disabled={disabled}
                  />
                  {includeWorkspaceTools ? (
                    <div className="mt-4">
                      <div className="layer-h">{t("experts.tools.workspaceGroup")}</div>
                      <p className="mb-2 text-sm text-muted-foreground">{t("experts.tools.workspaceIntro")}</p>
                      <ul className="grid gap-1">
                        {WORKSPACE_CHAT_TOOLS.map((id) => (
                          <li key={id}>
                            <label className="flex items-center gap-2 text-sm">
                              <input type="checkbox" checked disabled />
                              {t(WORKSPACE_TOOL_LABEL[id])}
                            </label>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {error ? (
                    <p className="mt-3 text-sm text-destructive" role="alert">
                      {error}
                    </p>
                  ) : null}
                </div>
                <div className="flex justify-end border-t border-[color:var(--border-hairline)] px-5 py-3">
                  <AdminButton
                    variant="secondary"
                    size="sm"
                    onClick={() => setOpen(false)}
                  >
                    {t("common.close")}
                  </AdminButton>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
