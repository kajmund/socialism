import { useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { cachedImageUrl, type ImageCacheEntry } from "@/api/messages"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"

type CachedImagePickerModalProps = {
  open: boolean
  entries: ImageCacheEntry[]
  selectedSha256: string | null
  onSelect: (entry: ImageCacheEntry) => void
  onClose: () => void
}

export function CachedImagePickerModal({
  open,
  entries,
  selectedSha256,
  onSelect,
  onClose,
}: CachedImagePickerModalProps) {
  const { t } = useLocale()
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
      aria-labelledby="cached-image-picker-title"
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
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <h2 id="cached-image-picker-title" className="text-base font-medium">
              {t("messages.workshop.imagePickModalTitle")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("messages.workshop.imagePickModalIntro")}
            </p>
          </div>
          <AdminButton variant="secondary" size="sm" onClick={onClose}>
            {t("common.close")}
          </AdminButton>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("messages.workshop.imagePickModalEmpty")}</p>
          ) : (
            <div
              role="listbox"
              aria-label={t("messages.workshop.imagePickCached")}
              className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
            >
              {entries.map((row) => {
                const selected = selectedSha256 === row.sha256
                return (
                  <button
                    key={row.sha256}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    aria-label={t("messages.workshop.imagePickOption", {
                      caption: row.caption.slice(0, 80),
                    })}
                    className={`overflow-hidden rounded border text-left transition-colors ${
                      selected
                        ? "border-db-ink-950 ring-2 ring-db-ink-950"
                        : "border-[color:var(--border-hairline)] hover:border-db-ink-950"
                    }`}
                    onClick={() => {
                      onSelect(row)
                      onClose()
                    }}
                  >
                    <img
                      src={cachedImageUrl(row.sha256)}
                      alt=""
                      className="aspect-[4/3] w-full object-cover"
                      loading="lazy"
                    />
                    <span className="line-clamp-2 px-2 py-1.5 text-xs text-muted-foreground">
                      {row.caption}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
