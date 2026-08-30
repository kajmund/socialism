import { Fragment, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Wrench } from "lucide-react"
import { AdminButton } from "@/components/ui/admin-button"
import {
  EXPERT_TOOLS,
  type ExpertToolGroup,
  type ExpertToolId,
} from "@/data/expert-tools"
import { useLocale, type MessageKey } from "@/i18n"

const GROUP_ORDER: ExpertToolGroup[] = ["company", "search"]

const GROUP_LABEL: Record<ExpertToolGroup, MessageKey> = {
  company: "experts.tools.groupCompany",
  search: "experts.tools.groupSearch",
}

const TOOL_LABEL: Record<ExpertToolId, MessageKey> = {
  search_companies: "experts.tools.search_companies",
  lookup_company: "experts.tools.lookup_company",
  validate_orgnr: "experts.tools.validate_orgnr",
  search_duckduckgo: "experts.tools.search_duckduckgo",
  search_wiki: "experts.tools.search_wiki",
}

export type ExpertToolsFieldsProps = {
  tools: ExpertToolId[]
  onChange: (tools: ExpertToolId[]) => void
  disabled?: boolean
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
    onChange(checked ? EXPERT_TOOLS.map((tool) => tool.id) : [])
  }

  function toggle(id: ExpertToolId, checked: boolean) {
    if (checked) {
      onChange([
        ...EXPERT_TOOLS.map((tool) => tool.id).filter(
          (name) => selected.has(name) || name === id,
        ),
      ])
      return
    }
    onChange(tools.filter((name) => name !== id))
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
                    {t("experts.composer.layerTools")}
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("experts.tools.intro")}
                  </p>
                </div>
                <div className="px-5 py-4">
                  <ExpertToolsTable
                    tools={tools}
                    onChange={onChange}
                    disabled={disabled}
                  />
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
