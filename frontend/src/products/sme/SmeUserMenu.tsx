import { LogOut, Settings } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { useLocale } from "@/i18n"
import { SmeAdminModal } from "@/products/sme/SmeAdminModal"

function userInitials(value: string): string {
  const name = value.split("@")[0] ?? value
  const parts = name.split(/[^a-zA-ZÀ-ÖØ-öø-ÿ]+/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`.toUpperCase()
  }
  return name.slice(0, 2).toUpperCase() || "--"
}

export function SmeUserMenu() {
  const { t } = useLocale()
  const { isAdmin, signOut, user } = useAuth()
  const [open, setOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const label = user?.username || user?.email || ""

  useEffect(() => {
    if (!open) return
    function closeOutside(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("pointerdown", closeOutside)
    window.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOutside)
      window.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  return (
    <>
      <div ref={rootRef} className="relative">
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full border border-db-gold-500 bg-db-gold-500 text-xs font-semibold text-db-navy-ink transition-colors hover:bg-db-gold-700"
          aria-label={t("sme.userMenuAria", { name: label })}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {userInitials(label)}
        </button>
        {open ? (
          <div
            className="absolute right-0 top-11 z-50 w-56 overflow-hidden rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 py-1 text-[color:var(--text-body)] shadow-[var(--shadow-lg)]"
            role="menu"
          >
            <p className="truncate border-b border-[color:var(--border-hairline)] px-3 py-2 text-xs text-[color:var(--text-muted)]">
              {label}
            </p>
            {isAdmin ? (
              <button
                type="button"
                className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm hover:bg-db-ink-100"
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  setAdminOpen(true)
                }}
              >
                <Settings size={17} aria-hidden="true" />
                {t("sme.admin")}
              </button>
            ) : null}
            <div className="mt-1 border-t border-[color:var(--border-hairline)] pt-1">
              <button
                type="button"
                className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm hover:bg-db-ink-100"
                role="menuitem"
                onClick={() => void signOut()}
              >
                <LogOut size={17} aria-hidden="true" />
                {t("sme.signOut")}
              </button>
            </div>
          </div>
        ) : null}
      </div>
      <SmeAdminModal open={adminOpen} onClose={() => setAdminOpen(false)} />
    </>
  )
}
