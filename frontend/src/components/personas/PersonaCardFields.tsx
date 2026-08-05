import { PersonaAnekdotEditor } from "@/components/personas/PersonaAnekdot"
import type { EditablePersona } from "@/data/library-types"
import { useLocale, type MessageKey } from "@/i18n"

export type CardFieldKey = Exclude<keyof EditablePersona, "key">

type CardFieldDef = {
  key: CardFieldKey
  labelKey: MessageKey
  kind: "age" | "select"
}

/** Catalog-backed compact fields — anekdot is edited separately (generativ, ej recept). */
const PERSONA_CARD_FIELDS: CardFieldDef[] = [
  { key: "age", labelKey: "personas.fields.age", kind: "age" },
  { key: "kön", labelKey: "personas.fields.gender", kind: "select" },
  { key: "ort", labelKey: "personas.fields.district", kind: "select" },
  { key: "yrke", labelKey: "personas.fields.occupation", kind: "select" },
  { key: "utbildning", labelKey: "personas.fields.education", kind: "select" },
  { key: "livssituation", labelKey: "personas.fields.lifeSituation", kind: "select" },
  { key: "lutning", labelKey: "personas.fields.leaning", kind: "select" },
  { key: "sakfragor", labelKey: "personas.fields.issues", kind: "select" },
  { key: "fortroende", labelKey: "personas.fields.trust", kind: "select" },
  { key: "ton", labelKey: "personas.fields.tone", kind: "select" },
  { key: "sprak", labelKey: "personas.fields.language", kind: "select" },
  { key: "medievanor", labelKey: "personas.fields.media", kind: "select" },
  { key: "parti", labelKey: "personas.fields.party", kind: "select" },
  { key: "valdeltagande", labelKey: "personas.fields.voting", kind: "select" },
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
  const { t } = useLocale()
  return (
    <div className="p-fields">
      {PERSONA_CARD_FIELDS.map((field) => {
        const value = profile[field.key] ?? ""
        const label = t(field.labelKey)
        if (field.kind === "age") {
          return (
            <label key={field.key} className="p-field">
              <span className="p-field-lbl">{label}</span>
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
            <span className="p-field-lbl">{label}</span>
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
