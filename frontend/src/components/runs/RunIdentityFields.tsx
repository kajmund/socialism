import { Link } from "react-router-dom"
import type { RunPopulationOption } from "@/data/runs-types"
import { useLocale } from "@/i18n"

export type RunIdentityFieldsProps = {
  name: string
  onNameChange: (value: string) => void
  startDate: string
  onStartDateChange: (value: string) => void
  populations: RunPopulationOption[]
  popId: number | null
  onPopIdChange: (id: number) => void
  population: RunPopulationOption
  popOpen: boolean
  onPopOpenChange: (open: boolean) => void
  allowPopulationCreatePost: boolean
  onAllowPopulationCreatePostChange: (value: boolean) => void
  disabled?: boolean
}

export function RunIdentityFields({
  name,
  onNameChange,
  startDate,
  onStartDateChange,
  populations,
  popId,
  onPopIdChange,
  population,
  popOpen,
  onPopOpenChange,
  allowPopulationCreatePost,
  onAllowPopulationCreatePostChange,
  disabled = false,
}: RunIdentityFieldsProps) {
  const { t } = useLocale()

  return (
    <>
      <div className="id-field">
        <label htmlFor="run-name">{t("runs.identity.nameLabel")}</label>
        <input
          id="run-name"
          value={name}
          disabled={disabled}
          onChange={(e) => onNameChange(e.target.value)}
        />
        <label className="id-check-row">
          <input
            id="run-create-post"
            type="checkbox"
            checked={allowPopulationCreatePost}
            disabled={disabled}
            onChange={(e) => onAllowPopulationCreatePostChange(e.target.checked)}
          />
          {t("runs.identity.allowCreatePost")}
        </label>
      </div>
      <div className="id-field">
        <label>{t("runs.identity.startDate")}</label>
        <input
          type="date"
          value={startDate}
          disabled={disabled}
          onChange={(e) => onStartDateChange(e.target.value)}
        />
      </div>
      <div className="id-field">
        <label>{t("runs.identity.population")}</label>
        <div
          className="pop-mini"
          onClick={() => {
            if (!disabled) onPopOpenChange(true)
          }}
        >
          <div className="cluster">
            {population.initials.map((ini) => (
              <div className="av" key={ini}>
                {ini}
              </div>
            ))}
          </div>
          <div className="info">
            <div className="nm">{population.name}</div>
            <div className="sub">
              {t("common.personasCount", { count: population.size })}
            </div>
          </div>
          <span className="swap">{t("runs.identity.swap")}</span>
          {popOpen && (
            <>
              <div
                className="pop-overlay"
                onClick={(e) => {
                  e.stopPropagation()
                  onPopOpenChange(false)
                }}
              />
              <div
                className="pop-dropdown"
                onClick={(e) => e.stopPropagation()}
              >
                {populations.map((p) => (
                  <div
                    key={p.id}
                    className={"pop-opt" + (p.id === popId ? " sel" : "")}
                    onClick={() => {
                      onPopIdChange(p.id)
                      onPopOpenChange(false)
                    }}
                  >
                    <div className="av">{p.initials[0]}</div>
                    <div className="nm">{p.name}</div>
                    <div className="sub">
                      {t("common.personasCount", { count: p.size })}
                    </div>
                  </div>
                ))}
                <div className="pop-dropdown-foot">
                  <Link to="/populations">{t("runs.identity.viewAll")}</Link>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
