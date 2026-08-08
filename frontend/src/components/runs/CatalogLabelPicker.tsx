import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { useLocale } from "@/i18n"

export type CatalogLabelOption = {
  label: string
  description?: string
}

type CatalogLabelPickerProps = {
  id: string
  fieldLabel: string
  options: CatalogLabelOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  allowCustom?: boolean
  emptyHint?: ReactNode
}

export function CatalogLabelPicker({
  id,
  fieldLabel,
  options,
  value,
  onChange,
  placeholder,
  allowCustom = true,
  emptyHint,
}: CatalogLabelPickerProps) {
  const { t } = useLocale()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [manual, setManual] = useState(
    () => Boolean(value.trim()) && !options.some((o) => o.label === value),
  )

  useEffect(() => {
    if (value.trim() && options.some((o) => o.label === value)) {
      setManual(false)
    }
  }, [options, value])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        (o.description ?? "").toLowerCase().includes(q),
    )
  }, [options, query])

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false)
        setQuery("")
      }
    }
    document.addEventListener("mousedown", onPointerDown)
    return () => document.removeEventListener("mousedown", onPointerDown)
  }, [open])

  function select(label: string) {
    onChange(label)
    setManual(false)
    setOpen(false)
    setQuery("")
  }

  function openPicker() {
    setOpen(true)
    setQuery("")
  }

  return (
    <div className="msg-lib-picker" ref={rootRef}>
      <label htmlFor={manual ? id : open ? `${id}-search` : id}>{fieldLabel}</label>
      {manual ? (
        <>
          <input
            id={id}
            className="msg-lib-search"
            placeholder={t("runs.tick.senderCustomPh")}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          {options.length > 0 && (
            <button
              type="button"
              className="catalog-picker-mode-link"
              onClick={() => {
                setManual(false)
                onChange("")
              }}
            >
              {t("runs.tick.senderFromCatalog")}
            </button>
          )}
        </>
      ) : (
        <>
          <div className="msg-lib-control">
            {open ? (
              <>
                <input
                  id={`${id}-search`}
                  className="msg-lib-search"
                  type="search"
                  autoFocus
                  placeholder={t("runs.tick.senderSearch")}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setOpen(false)
                      setQuery("")
                    }
                  }}
                  aria-controls={`${id}-listbox`}
                  aria-expanded
                  aria-autocomplete="list"
                  role="combobox"
                />
                <div
                  id={`${id}-listbox`}
                  className="msg-lib-list"
                  role="listbox"
                  aria-label={fieldLabel}
                >
                  {filtered.map((o) => (
                    <button
                      key={o.label}
                      type="button"
                      role="option"
                      aria-selected={o.label === value}
                      className={"msg-lib-opt" + (o.label === value ? " sel" : "")}
                      onClick={() => select(o.label)}
                    >
                      <span className="msg-lib-title">{o.label}</span>
                      {o.description?.trim() ? (
                        <span className="msg-lib-snippet">{o.description}</span>
                      ) : null}
                    </button>
                  ))}
                  {filtered.length === 0 ? (
                    <div className="msg-lib-empty">
                      {query.trim()
                        ? t("runs.tick.senderNoMatch", { query: query.trim() })
                        : t("runs.tick.senderNoOptions")}
                    </div>
                  ) : null}
                </div>
              </>
            ) : (
              <button
                type="button"
                id={id}
                className="msg-lib-trigger"
                onClick={openPicker}
                aria-haspopup="listbox"
                aria-expanded={false}
              >
                <span className="msg-lib-trigger-label">
                  {value.trim() || placeholder || t("runs.tick.pickPlaceholder")}
                </span>
                <span className="msg-lib-caret" aria-hidden>
                  ▾
                </span>
              </button>
            )}
          </div>
          {allowCustom && (
            <button
              type="button"
              className="catalog-picker-mode-link"
              onClick={() => setManual(true)}
            >
              {t("runs.tick.senderWriteOwn")}
            </button>
          )}
        </>
      )}
      {options.length === 0 && emptyHint ? (
        <p className="inj-source">{emptyHint}</p>
      ) : null}
    </div>
  )
}

export function CatalogSenderEmptyHint() {
  const { t } = useLocale()

  return (
    <>
      {t("runs.tick.senderEmptyPrefix")}{" "}
      <Link to="/tools/configurations">{t("runs.tick.senderEmptyLink")}</Link>
    </>
  )
}
