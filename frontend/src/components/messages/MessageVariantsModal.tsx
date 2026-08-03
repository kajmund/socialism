import { useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import type { MessageVariant } from "@/api/messages"
import { AdminButton } from "@/components/ui/admin-button"

type MessageVariantsModalProps = {
  open: boolean
  generating: boolean
  error: string | null
  variants: MessageVariant[]
  audience: string
  purpose: string
  tone: string
  onAudienceChange: (value: string) => void
  onPurposeChange: (value: string) => void
  onToneChange: (value: string) => void
  onGenerate: () => void
  onSelect: (variant: MessageVariant) => void
  onClose: () => void
}

export function MessageVariantsModal({
  open,
  generating,
  error,
  variants,
  audience,
  purpose,
  tone,
  onAudienceChange,
  onPurposeChange,
  onToneChange,
  onGenerate,
  onSelect,
  onClose,
}: MessageVariantsModalProps) {
  const overlayMouseDownRef = useRef(false)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="variants-modal-title"
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <h2 id="variants-modal-title" className="text-base font-medium">
              Generera varianter
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Tre formuleringar utifrån texten i verkstaden. Välj en så ersätter den
              budskapstexten.
            </p>
          </div>
          <AdminButton variant="secondary" size="sm" onClick={onClose}>
            Stäng
          </AdminButton>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          <div className="form-grid">
            <div className="field">
              <label htmlFor="variant-audience">Målgrupp (valfritt)</label>
              <input
                id="variant-audience"
                value={audience}
                onChange={(e) => onAudienceChange(e.target.value)}
                placeholder="t.ex. småbarnsföräldrar i Norrköping"
              />
            </div>
            <div className="field">
              <label htmlFor="variant-purpose">Syfte (valfritt)</label>
              <input
                id="variant-purpose"
                value={purpose}
                onChange={(e) => onPurposeChange(e.target.value)}
                placeholder="t.ex. bygga auktoritet / testa reaktion"
              />
            </div>
            <div className="field">
              <label htmlFor="variant-tone">Tonläge (valfritt)</label>
              <input
                id="variant-tone"
                value={tone}
                onChange={(e) => onToneChange(e.target.value)}
                placeholder="t.ex. saklig, varm, skarp"
              />
            </div>
          </div>

          <div className="mt-4">
            <AdminButton onClick={onGenerate} disabled={generating}>
              {generating ? "Genererar…" : "Generera tre varianter"}
            </AdminButton>
          </div>

          {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

          {variants.length > 0 && (
            <div className="mt-5 space-y-3">
              <h3 className="text-sm font-medium">Välj en variant</h3>
              <div className="grid gap-3 md:grid-cols-3">
                {variants.map((v) => (
                  <button
                    key={v.key}
                    type="button"
                    onClick={() => onSelect(v)}
                    className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] p-3 text-left text-sm transition-colors hover:border-db-gold-500 hover:bg-db-gold-500/10"
                  >
                    <div className="mb-2 font-medium">{v.label}</div>
                    <p className="whitespace-pre-wrap text-muted-foreground line-clamp-8">
                      {v.body}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
