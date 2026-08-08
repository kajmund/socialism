import { useEffect, useRef } from "react"
import type { OasisRunOptions } from "@/data/runs-types"
import { useLocale } from "@/i18n"

export type RunAgentToolsFieldsProps = {
  options: OasisRunOptions
  onChange: (options: OasisRunOptions) => void
  disabled?: boolean
}

export function RunAgentToolsFields({
  options,
  onChange,
  disabled = false,
}: RunAgentToolsFieldsProps) {
  const { t } = useLocale()
  const selectAllRef = useRef<HTMLInputElement>(null)

  const flags = [
    options.enable_search_duckduckgo,
    options.enable_search_wiki,
    options.enable_sympy_tools,
  ] as const
  const allSelected = flags.every(Boolean)
  const someSelected = flags.some(Boolean)

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected && !allSelected
    }
  }, [allSelected, someSelected])

  function setAll(checked: boolean) {
    onChange({
      ...options,
      enable_search_duckduckgo: checked,
      enable_search_wiki: checked,
      enable_sympy_tools: checked,
    })
  }

  return (
    <div className="id-field">
      <span className="block text-[13px] font-medium text-[color:var(--text-body)]">
        {t("runs.tools.heading")}
      </span>
      <p className="mt-1 mb-0 text-xs text-muted-foreground">{t("runs.tools.intro")}</p>
      <label className="id-check-row">
        <input
          ref={selectAllRef}
          id="run-tools-select-all"
          type="checkbox"
          checked={allSelected}
          disabled={disabled}
          onChange={(e) => setAll(e.target.checked)}
        />
        {t("runs.tools.selectAll")}
      </label>
      <label className="id-check-row">
        <input
          id="run-search-duckduckgo"
          type="checkbox"
          checked={options.enable_search_duckduckgo}
          disabled={disabled}
          onChange={(e) =>
            onChange({
              ...options,
              enable_search_duckduckgo: e.target.checked,
            })
          }
        />
        {t("runs.tools.enableSearchDuckduckgo")}
      </label>
      <label className="id-check-row">
        <input
          id="run-search-wiki"
          type="checkbox"
          checked={options.enable_search_wiki}
          disabled={disabled}
          onChange={(e) =>
            onChange({
              ...options,
              enable_search_wiki: e.target.checked,
            })
          }
        />
        {t("runs.tools.enableSearchWiki")}
      </label>
      <label className="id-check-row">
        <input
          id="run-sympy-tools"
          type="checkbox"
          checked={options.enable_sympy_tools}
          disabled={disabled}
          onChange={(e) =>
            onChange({
              ...options,
              enable_sympy_tools: e.target.checked,
            })
          }
        />
        {t("runs.tools.enableSympyTools")}
      </label>
    </div>
  )
}
