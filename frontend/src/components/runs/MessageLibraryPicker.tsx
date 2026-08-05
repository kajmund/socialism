import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import type { Message } from "@/api/messages"
import { useLocale } from "@/i18n"

type MessageLibraryPickerProps = {
  id: string
  messages: Message[]
  value: string | null
  onChange: (messageId: string | null) => void
  error?: string | null
  emptyHint?: ReactNode
}

export function MessageLibraryPicker({
  id,
  messages,
  value,
  onChange,
  error,
  emptyHint,
}: MessageLibraryPickerProps) {
  const { t } = useLocale()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")

  const selected = useMemo(
    () => messages.find((m) => m.id === value) ?? null,
    [messages, value],
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return messages
    return messages.filter(
      (m) =>
        m.title.toLowerCase().includes(q) || m.body.toLowerCase().includes(q),
    )
  }, [messages, query])

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

  function select(messageId: string | null) {
    onChange(messageId)
    setOpen(false)
    setQuery("")
  }

  function openPicker() {
    setOpen(true)
    setQuery("")
  }

  return (
    <div className="msg-lib-picker" ref={rootRef}>
      <label htmlFor={open ? `${id}-search` : id}>
        {t("runs.tick.libLabel")}
      </label>
      <div className="msg-lib-control">
        {open ? (
          <>
            <input
              id={`${id}-search`}
              className="msg-lib-search"
              type="search"
              autoFocus
              placeholder={t("runs.tick.libSearch")}
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
              aria-label={t("runs.tick.libLabel")}
            >
              <button
                type="button"
                role="option"
                aria-selected={value == null}
                className={"msg-lib-opt" + (value == null ? " sel" : "")}
                onClick={() => select(null)}
              >
                <span className="msg-lib-title">{t("runs.tick.libNone")}</span>
              </button>
              {filtered.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="option"
                  aria-selected={m.id === value}
                  className={"msg-lib-opt" + (m.id === value ? " sel" : "")}
                  onClick={() => select(m.id)}
                >
                  <span className="msg-lib-title">{m.title}</span>
                  {m.body.trim() ? (
                    <span className="msg-lib-snippet">
                      {m.body.trim().slice(0, 96)}
                      {m.body.trim().length > 96 ? "…" : ""}
                    </span>
                  ) : null}
                </button>
              ))}
              {filtered.length === 0 ? (
                <div className="msg-lib-empty">
                  {query.trim()
                    ? t("runs.tick.libNoMatch", { query: query.trim() })
                    : t("runs.tick.libEmpty")}
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
              {selected?.title ?? t("runs.tick.libPick")}
            </span>
            <span className="msg-lib-caret" aria-hidden>
              ▾
            </span>
          </button>
        )}
      </div>
      {error && <p className="inj-source">{error}</p>}
      {!error && messages.length === 0 && emptyHint ? (
        <p className="inj-source">{emptyHint}</p>
      ) : null}
    </div>
  )
}
