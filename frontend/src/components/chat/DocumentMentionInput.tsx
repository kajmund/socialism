import { useEffect, useId, useRef, useState, type RefObject } from "react"
import { useLocale } from "@/i18n"
import {
  activeDocumentQuery,
  documentMentionChoices,
  insertDocumentMention,
} from "@/products/sme/documentMentions"

type MentionFile = { id: string; filename: string }

export function DocumentMentionInput({
  inputRef,
  value,
  onChange,
  onSubmit,
  disabled,
  placeholder,
  files,
}: {
  inputRef: RefObject<HTMLInputElement | null>
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  placeholder: string
  files?: MentionFile[]
}) {
  const { t } = useLocale()
  const listId = useId()
  const [caret, setCaret] = useState(value.length)
  const [activeIndex, setActiveIndex] = useState(0)
  const [dismissedKey, setDismissedKey] = useState<string | null>(null)
  const pendingCaret = useRef<number | null>(null)
  const activeOption = useRef<HTMLButtonElement | null>(null)
  const enabled = Boolean(files?.length)
  const active = enabled ? activeDocumentQuery(value, caret) : null
  const choices = active && files ? documentMentionChoices(files, active.query) : []
  const menuKey = active ? `${active.start}:${active.query}` : null
  const open = Boolean(menuKey && menuKey !== dismissedKey && choices.length > 0)
  const selected = Math.min(activeIndex, Math.max(choices.length - 1, 0))

  useEffect(() => {
    setActiveIndex(0)
  }, [menuKey])

  useEffect(() => {
    const next = pendingCaret.current
    if (next == null) return
    pendingCaret.current = null
    const input = inputRef.current
    if (!input) return
    input.focus()
    input.setSelectionRange(next, next)
    setCaret(next)
  }, [value, inputRef])

  useEffect(() => {
    if (open) activeOption.current?.scrollIntoView({ block: "nearest" })
  }, [open, selected, menuKey])

  function syncCaret(target: HTMLInputElement) {
    setCaret(target.selectionStart ?? target.value.length)
  }

  function choose(filename: string) {
    const next = insertDocumentMention(value, caret, filename)
    if (!next) return
    pendingCaret.current = next.caret
    setCaret(next.caret)
    onChange(next.text)
  }

  return (
    <div className="relative min-w-0 flex-1">
      {open ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={t("voiceWorkspaceChat.mentionDocuments")}
          className="absolute bottom-full left-0 z-20 mb-1 max-h-48 w-full overflow-auto rounded-lg border border-[color:var(--border-hairline)] bg-white py-1 shadow-md"
        >
          {choices.map((file, index) => (
            <li key={file.id} role="presentation">
              <button
                ref={index === selected ? activeOption : undefined}
                id={`${listId}-${file.id}`}
                type="button"
                role="option"
                aria-selected={index === selected}
                aria-label={t("voiceWorkspaceChat.mentionDocumentOption", { name: file.filename })}
                className={`block w-full truncate px-3 py-2 text-left text-sm ${index === selected ? "bg-db-ink-950 text-db-gold-500" : "hover:bg-db-ink-50"}`}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(file.filename)}
              >
                {file.filename}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <input
        ref={inputRef}
        className="w-full min-w-0"
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        role={enabled ? "combobox" : undefined}
        aria-expanded={enabled ? open : undefined}
        aria-controls={open ? listId : undefined}
        aria-autocomplete={enabled ? "list" : undefined}
        aria-activedescendant={open ? `${listId}-${choices[selected]?.id ?? ""}` : undefined}
        onChange={(event) => {
          syncCaret(event.target)
          onChange(event.target.value)
        }}
        onSelect={(event) => syncCaret(event.currentTarget)}
        onClick={(event) => syncCaret(event.currentTarget)}
        onKeyUp={(event) => syncCaret(event.currentTarget)}
        onFocus={() => setDismissedKey(null)}
        onBlur={() => setDismissedKey(menuKey)}
        onKeyDown={(event) => {
          if (open) {
            if (event.key === "ArrowDown") {
              event.preventDefault()
              setActiveIndex((index) => (index + 1) % choices.length)
              return
            }
            if (event.key === "ArrowUp") {
              event.preventDefault()
              setActiveIndex((index) => (index - 1 + choices.length) % choices.length)
              return
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault()
              const choice = choices[selected]
              if (choice) choose(choice.filename)
              return
            }
            if (event.key === "Escape") {
              event.preventDefault()
              setDismissedKey(menuKey)
              return
            }
          }
          if (event.key === "Enter") {
            event.preventDefault()
            onSubmit()
          }
        }}
      />
    </div>
  )
}
