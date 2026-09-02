import { useMemo } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { useLocale } from "@/i18n"
import { modulesWith } from "@/modules/moduleRegistry"

type ExpertPanelModulePickerProps = {
  value: readonly string[]
  onChange: (next: string[]) => void
  disabled?: boolean
}

export function ExpertPanelModulePicker({
  value,
  onChange,
  disabled,
}: ExpertPanelModulePickerProps) {
  const { t } = useLocale()
  const { resolvedModules } = useAuth()
  const options = useMemo(
    () => modulesWith("panel_engine", resolvedModules),
    [resolvedModules],
  )

  if (options.length === 0) return null

  return (
    <fieldset className="field mt-4 border-0 p-0">
      <legend className="mb-1 text-sm font-medium">{t("expertPanels.modules.label")}</legend>
      <p className="mb-3 text-sm text-muted-foreground">{t("expertPanels.modules.hint")}</p>
      <div className="flex flex-col gap-2">
        {options.map((mod) => {
          const checked = value.includes(mod.id)
          return (
            <label key={mod.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) => {
                  if (event.target.checked) onChange([...value, mod.id])
                  else onChange(value.filter((id) => id !== mod.id))
                }}
              />
              {t(mod.nameKey)}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
