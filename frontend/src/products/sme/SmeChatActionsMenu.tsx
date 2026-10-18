import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { Menu } from "lucide-react"
import { useLocale } from "@/i18n"

export function SmeChatActionsMenu({ children }: { children: ReactNode }) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const panelId = useId()
  useLayoutEffect(() => {
    if (!open) return
    function place() {
      const rect = root.current?.getBoundingClientRect()
      if (!rect) return
      setPosition({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) })
    }
    place()
    window.addEventListener("resize", place)
    window.addEventListener("scroll", place, true)
    return () => {
      window.removeEventListener("resize", place)
      window.removeEventListener("scroll", place, true)
    }
  }, [open])
  useEffect(() => {
    if (!open) return
    function outside(event: MouseEvent) {
      const target = event.target
      if (!(target instanceof Node)) return
      if (root.current?.contains(target) || panel.current?.contains(target)) return
      setOpen(false)
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("mousedown", outside)
      document.removeEventListener("keydown", escape)
    }
  }, [open])

  const menu = <div id={panelId} ref={panel} role="menu" className={open ? "fixed z-40 grid w-64 gap-2 rounded-lg border bg-white p-2 shadow-lg" : "hidden"} style={open && position ? { top: position.top, right: position.right } : undefined} onClick={() => setOpen(false)}>
    {children}
  </div>

  return <div className="relative shrink-0" ref={root}>
    <button type="button" className="grid size-9 place-items-center rounded-lg border" aria-label={t("sme.chatMenu")} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((current) => !current)}>
      <Menu size={17} />
    </button>
    {typeof document === "undefined" ? menu : createPortal(menu, document.body)}
  </div>
}
