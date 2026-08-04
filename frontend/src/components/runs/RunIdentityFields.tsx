import { Link } from "react-router-dom"
import type { RunPopulationOption } from "@/data/runs-types"

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
  return (
    <>
      <div className="id-field">
        <label htmlFor="run-name">Namn / scenario-id</label>
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
          Låt populationen skapa egna inlägg
        </label>
      </div>
      <div className="id-field">
        <label>Startdatum</label>
        <input
          type="date"
          value={startDate}
          disabled={disabled}
          onChange={(e) => onStartDateChange(e.target.value)}
        />
      </div>
      <div className="id-field">
        <label>Population</label>
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
            <div className="sub">{population.size} personas</div>
          </div>
          <span className="swap">Byt ▾</span>
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
                    <div className="sub">{p.size} personas</div>
                  </div>
                ))}
                <div className="pop-dropdown-foot">
                  <Link to="/populations">Visa alla populationer →</Link>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
