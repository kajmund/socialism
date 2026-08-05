import type { EditablePersona } from "@/data/library-types"
import { personaAnekdot } from "@/data/library"
import { useLocale } from "@/i18n"

type PersonaAnekdotEditorProps = {
  value: string
  disabled?: boolean
  onChange: (value: string) => void
  className?: string
}

export function PersonaAnekdotEditor({
  value,
  disabled,
  onChange,
  className = "p-field-ctl",
}: PersonaAnekdotEditorProps) {
  const { t } = useLocale()
  return (
    <label className="p-field p-field-span2">
      <span className="p-field-lbl">{t("personas.fields.anecdote")}</span>
      <textarea
        className={className + " min-h-[4.5rem] resize-y"}
        rows={3}
        placeholder={t("personas.fields.anecdotePlaceholder")}
        value={value === "—" ? "" : value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value.trim() ? e.target.value : "—")}
      />
    </label>
  )
}

type PersonaAnekdotPresentationProps = {
  profile: Pick<EditablePersona, "anekdot">
}

export function PersonaAnekdotPresentation({ profile }: PersonaAnekdotPresentationProps) {
  const { t } = useLocale()
  const text = personaAnekdot(profile)
  if (!text) return null
  return (
    <div className="p-sec">
      <div className="p-num">V.</div>
      <div className="p-lbl">{t("personas.fields.everydayDetail")}</div>
      <p>
        <i>{text}</i>
      </p>
    </div>
  )
}
