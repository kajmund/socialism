import { useEffect, useRef } from "react"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import type { GeoBounds } from "@/api/catalog"
import { useLocale } from "@/i18n"

const DEFAULT_MAP_CENTER: L.LatLngExpression = [58.5877, 16.1924]
const DEFAULT_ZOOM = 11

type DistrictMapPreviewProps = {
  bounds: GeoBounds | null
  label: string
  onOpen: () => void
}

export function DistrictMapPreview({
  bounds,
  label,
  onOpen,
}: DistrictMapPreviewProps) {
  const { t } = useLocale()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const rectRef = useRef<L.Rectangle | null>(null)
  const hasBounds = bounds !== null

  useEffect(() => {
    if (!hasBounds) return
    const el = containerRef.current
    if (!el) return

    const map = L.map(el, {
      center: DEFAULT_MAP_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
    })
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
    }).addTo(map)
    mapRef.current = map

    const timers = [0, 80, 200].map((ms) =>
      window.setTimeout(() => map.invalidateSize(), ms),
    )

    return () => {
      for (const t of timers) window.clearTimeout(t)
      map.remove()
      mapRef.current = null
      rectRef.current = null
    }
  }, [hasBounds])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !bounds) return

    if (rectRef.current) {
      map.removeLayer(rectRef.current)
      rectRef.current = null
    }

    const llb = L.latLngBounds(
      L.latLng(bounds.south, bounds.west),
      L.latLng(bounds.north, bounds.east),
    )
    rectRef.current = L.rectangle(llb, {
      color: "#c9a227",
      weight: 2,
      fillOpacity: 0.28,
      interactive: false,
    }).addTo(map)
    map.fitBounds(llb.pad(0.4), { maxZoom: 14, animate: false })
    window.setTimeout(() => map.invalidateSize(), 0)
  }, [bounds])

  if (!bounds) {
    return (
      <button
        type="button"
        onClick={onOpen}
        className="flex h-full min-h-[140px] w-full flex-col items-center justify-center gap-1 rounded border border-dashed border-[color:var(--border-hairline)] bg-[color:var(--db-ink-0)] px-3 text-center text-xs text-muted-foreground hover:border-[color:var(--db-gold)] hover:text-[color:var(--text-body)]"
        aria-label={t("config.map.setAreaFor", { label: label || t("config.map.districtFallback") })}
      >
        <span className="font-medium">{t("config.map.noMap")}</span>
        <span>{t("config.map.clickToDraw")}</span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative z-0 isolate block h-full min-h-[140px] w-full overflow-hidden rounded border border-[color:var(--border-hairline)] text-left"
      aria-label={t("config.map.editAreaFor", { label: label || t("config.map.districtFallback") })}
    >
      <div ref={containerRef} className="pointer-events-none absolute inset-0" />
      <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent px-2 pb-1.5 pt-5 text-[11px] text-white opacity-0 transition-opacity group-hover:opacity-100">
        {t("config.map.clickToEdit")}
      </span>
    </button>
  )
}
