import type { EditablePersona } from "@/data/library-types"
import { PersonaAnekdotEditor } from "@/components/personas/PersonaAnekdot"

export type CardFieldKey = keyof EditablePersona

type CardFieldDef = {
  key: CardFieldKey
  label: string
  kind: "age" | "select"
}

/** Catalog-backed compact fields — anekdot is edited separately (generativ, ej recept). */
export const PERSONA_CARD_FIELDS: CardFieldDef[] = [
  { key: "age", label: "Ålder", kind: "age" },
  { key: "kön", label: "Kön", kind: "select" },
  { key: "ort", label: "Distrikt", kind: "select" },
  { key: "yrke", label: "Yrke", kind: "select" },
  { key: "utbildning", label: "Utbildning", kind: "select" },
  { key: "livssituation", label: "Livssituation", kind: "select" },
  { key: "lutning", label: "Lutning", kind: "select" },
  { key: "sakfragor", label: "Sakfrågor", kind: "select" },
  { key: "fortroende", label: "Förtroende", kind: "select" },
  { key: "ton", label: "Ton", kind: "select" },
  { key: "sprak", label: "Språk", kind: "select" },
  { key: "medievanor", label: "Media", kind: "select" },
  { key: "parti", label: "Parti", kind: "select" },
  { key: "valdeltagande", label: "Val", kind: "select" },
]

type PersonaCardFieldsProps = {
  profile: EditablePersona
  fieldOptions: Record<string, string[]>
  disabled?: boolean
  onChange: (key: CardFieldKey, value: string) => void
}

export function PersonaCardFields({
  profile,
  fieldOptions,
  disabled,
  onChange,
}: PersonaCardFieldsProps) {
  return (
    <div className="p-fields">
      {PERSONA_CARD_FIELDS.map((field) => {
        const value = profile[field.key] ?? ""
        if (field.kind === "age") {
          return (
            <label key={field.key} className="p-field">
              <span className="p-field-lbl">{field.label}</span>
              <input
                className="p-field-ctl"
                type="number"
                min={16}
                max={100}
                inputMode="numeric"
                value={value === "—" ? "" : value}
                disabled={disabled}
                onChange={(e) => onChange(field.key, e.target.value)}
              />
            </label>
          )
        }
        const opts = fieldOptions[field.key] ?? []
        return (
          <label key={field.key} className="p-field">
            <span className="p-field-lbl">{field.label}</span>
            <select
              className="p-field-ctl"
              value={value}
              disabled={disabled || opts.length === 0}
              onChange={(e) => onChange(field.key, e.target.value)}
            >
              {!opts.includes(value) && (
                <option value={value}>{value || "—"}</option>
              )}
              {opts.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        )
      })}
      <PersonaAnekdotEditor
        value={profile.anekdot ?? "—"}
        disabled={disabled}
        onChange={(v) => onChange("anekdot", v)}
      />
    </div>
  )
}
