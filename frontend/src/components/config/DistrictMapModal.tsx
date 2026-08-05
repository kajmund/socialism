import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import type { CatalogItem, GeoBounds } from "@/api/catalog"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"

const NORRKOPING: L.LatLngExpression = [58.5877, 16.1924]
const DEFAULT_ZOOM = 12

type DistrictMapModalProps = {
  open: boolean
  district: CatalogItem
  others: CatalogItem[]
  onClose: () => void
  onChangeBounds: (bounds: GeoBounds | null) => void
}

function toLatLngBounds(b: GeoBounds): L.LatLngBounds {
  return L.latLngBounds(L.latLng(b.south, b.west), L.latLng(b.north, b.east))
}

function fromLatLngBounds(b: L.LatLngBounds): GeoBounds {
  return {
    south: b.getSouth(),
    west: b.getWest(),
    north: b.getNorth(),
    east: b.getEast(),
  }
}

function isTiny(bounds: L.LatLngBounds): boolean {
  return (
    Math.abs(bounds.getNorth() - bounds.getSouth()) < 0.0008 ||
    Math.abs(bounds.getEast() - bounds.getWest()) < 0.0008
  )
}

function cornerIcon(cursor: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:12px;height:12px;background:#fff;border:2px solid #c9a227;box-shadow:0 0 0 1px #111;cursor:${cursor}"></div>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  })
}

export function DistrictMapModal({
  open,
  district,
  others,
  onClose,
  onChangeBounds,
}: DistrictMapModalProps) {
  const { t } = useLocale()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const otherLayerRef = useRef<L.LayerGroup | null>(null)
  const activeLayerRef = useRef<L.LayerGroup | null>(null)
  const draftRectRef = useRef<L.Rectangle | null>(null)
  const drawStartRef = useRef<L.LatLng | null>(null)
  const drawingRef = useRef(false)
  const fittedRef = useRef(false)
  const overlayMouseDownRef = useRef(false)
  const onChangeRef = useRef(onChangeBounds)

  const [drawing, setDrawing] = useState(false)

  onChangeRef.current = onChangeBounds
  drawingRef.current = drawing

  // Lock body scroll while open.
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      setDrawing(false)
      fittedRef.current = false
    }
  }, [open])

  // Create / destroy map when modal opens.
  useEffect(() => {
    if (!open) return
    const el = containerRef.current
    if (!el) return

    const map = L.map(el, {
      center: NORRKOPING,
      zoom: DEFAULT_ZOOM,
      boxZoom: false,
    })
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 18,
    }).addTo(map)

    const othersLayer = L.layerGroup().addTo(map)
    const activeLayer = L.layerGroup().addTo(map)
    mapRef.current = map
    otherLayerRef.current = othersLayer
    activeLayerRef.current = activeLayer

    const timers = [0, 50, 150, 300].map((ms) =>
      window.setTimeout(() => map.invalidateSize(), ms),
    )

    function clearDraft() {
      if (draftRectRef.current) {
        map.removeLayer(draftRectRef.current)
        draftRectRef.current = null
      }
      drawStartRef.current = null
    }

    function finishDraw(end: L.LatLng) {
      const start = drawStartRef.current
      if (!start) return
      const bounds = L.latLngBounds(start, end)
      clearDraft()
      if (isTiny(bounds)) return
      onChangeRef.current(fromLatLngBounds(bounds))
      setDrawing(false)
    }

    // DOM-level listeners: pan is disabled in drawing mode, so mouse events
    // are ours alone and can't race Leaflet's drag handler.
    function onDomMouseDown(ev: MouseEvent) {
      if (!drawingRef.current || ev.button !== 0) return
      ev.preventDefault()
      ev.stopPropagation()
      clearDraft()
      drawStartRef.current = map.mouseEventToLatLng(ev)
      draftRectRef.current = L.rectangle(
        L.latLngBounds(drawStartRef.current, drawStartRef.current),
        {
          color: "#c9a227",
          weight: 2,
          fillOpacity: 0.25,
          dashArray: "6 4",
          interactive: false,
        },
      ).addTo(map)
    }

    function onDomMouseMove(ev: MouseEvent) {
      if (!drawStartRef.current || !draftRectRef.current) return
      draftRectRef.current.setBounds(
        L.latLngBounds(drawStartRef.current, map.mouseEventToLatLng(ev)),
      )
    }

    function onDomMouseUp(ev: MouseEvent) {
      if (!drawStartRef.current) return
      finishDraw(map.mouseEventToLatLng(ev))
    }

    el.addEventListener("mousedown", onDomMouseDown, true)
    document.addEventListener("mousemove", onDomMouseMove)
    document.addEventListener("mouseup", onDomMouseUp)

    return () => {
      for (const t of timers) window.clearTimeout(t)
      el.removeEventListener("mousedown", onDomMouseDown, true)
      document.removeEventListener("mousemove", onDomMouseMove)
      document.removeEventListener("mouseup", onDomMouseUp)
      map.remove()
      mapRef.current = null
      otherLayerRef.current = null
      activeLayerRef.current = null
      draftRectRef.current = null
      drawStartRef.current = null
    }
  }, [open])

  // Drawing mode: freeze pan so drag draws instead of moving the map.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (drawing) {
      map.dragging.disable()
      map.getContainer().style.cursor = "crosshair"
    } else {
      map.dragging.enable()
      map.getContainer().style.cursor = ""
      if (draftRectRef.current) {
        map.removeLayer(draftRectRef.current)
        draftRectRef.current = null
      }
      drawStartRef.current = null
    }
  }, [drawing, open])

  // Paint other districts + active rectangle (movable body + resize corners).
  useEffect(() => {
    if (!open) return
    const map = mapRef.current
    const othersLayer = otherLayerRef.current
    const activeLayer = activeLayerRef.current
    if (!map || !othersLayer || !activeLayer) return

    othersLayer.clearLayers()
    activeLayer.clearLayers()

    for (const item of others) {
      if (!item.bounds) continue
      L.rectangle(toLatLngBounds(item.bounds), {
        color: "#6b7280",
        weight: 1.5,
        fillOpacity: 0.06,
        interactive: false,
      })
        .bindTooltip(item.label || t("common.emDash"), { sticky: true })
        .addTo(othersLayer)
    }

    if (district.bounds && !drawing) {
      const bounds = toLatLngBounds(district.bounds)
      const rect = L.rectangle(bounds, {
        color: "#c9a227",
        weight: 2.5,
        fillOpacity: 0.22,
      }).addTo(activeLayer)

      const cornerDefs: Array<["n" | "s", "w" | "e", string]> = [
        ["n", "w", "nwse-resize"],
        ["n", "e", "nesw-resize"],
        ["s", "w", "nesw-resize"],
        ["s", "e", "nwse-resize"],
      ]
      const cornerMarkers: Array<{ ns: "n" | "s"; we: "w" | "e"; marker: L.Marker }> = []

      function cornerLatLng(b: L.LatLngBounds, ns: "n" | "s", we: "w" | "e"): L.LatLng {
        return L.latLng(
          ns === "n" ? b.getNorth() : b.getSouth(),
          we === "w" ? b.getWest() : b.getEast(),
        )
      }

      function syncCorners() {
        const b = rect.getBounds()
        for (const c of cornerMarkers) {
          c.marker.setLatLng(cornerLatLng(b, c.ns, c.we))
        }
      }

      function commit() {
        const b = rect.getBounds()
        if (isTiny(b)) {
          onChangeRef.current(district.bounds)
          return
        }
        onChangeRef.current(fromLatLngBounds(b))
      }

      // Drag rectangle body to move it.
      rect.on("mousedown", (e: L.LeafletMouseEvent) => {
        if (drawingRef.current) return
        L.DomEvent.stopPropagation(e)
        L.DomEvent.preventDefault(e.originalEvent)
        map.dragging.disable()
        const startCursor = e.latlng
        const startBounds = rect.getBounds()

        function onMove(ev: MouseEvent) {
          const cur = map.mouseEventToLatLng(ev)
          const dLat = cur.lat - startCursor.lat
          const dLng = cur.lng - startCursor.lng
          rect.setBounds(
            L.latLngBounds(
              [startBounds.getSouth() + dLat, startBounds.getWest() + dLng],
              [startBounds.getNorth() + dLat, startBounds.getEast() + dLng],
            ),
          )
          syncCorners()
        }

        function onUp() {
          document.removeEventListener("mousemove", onMove)
          map.dragging.enable()
          commit()
        }

        document.addEventListener("mousemove", onMove)
        document.addEventListener("mouseup", onUp, { once: true })
      })
      rect.on("add", () => {
        const elRect = rect.getElement() as HTMLElement | null
        if (elRect) elRect.style.cursor = "move"
      })

      for (const [ns, we, cursor] of cornerDefs) {
        const marker = L.marker(cornerLatLng(bounds, ns, we), {
          icon: cornerIcon(cursor),
          draggable: true,
          zIndexOffset: 700,
        }).addTo(activeLayer)
        cornerMarkers.push({ ns, we, marker })

        marker.on("dragstart", () => map.dragging.disable())
        marker.on("drag", () => {
          const p = marker.getLatLng()
          const b = rect.getBounds()
          const south = ns === "s" ? p.lat : b.getSouth()
          const north = ns === "n" ? p.lat : b.getNorth()
          const west = we === "w" ? p.lng : b.getWest()
          const east = we === "e" ? p.lng : b.getEast()
          if (south >= north || west >= east) return
          rect.setBounds(L.latLngBounds([south, west], [north, east]))
          syncCorners()
        })
        marker.on("dragend", () => {
          map.dragging.enable()
          commit()
        })
      }

      if (!fittedRef.current) {
        map.fitBounds(bounds.pad(0.35), { maxZoom: 14, animate: false })
        fittedRef.current = true
      }
    } else if (!district.bounds && !fittedRef.current) {
      map.setView(NORRKOPING, DEFAULT_ZOOM, { animate: false })
      fittedRef.current = true
    }
  }, [open, district.bounds, district.label, others, drawing, t])

  if (!open) return null

  const hasBounds = Boolean(district.bounds)

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("config.map.mapAriaLabel", { label: district.label || t("config.map.districtFallback") })}
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose()
      }}
    >
      <div className="flex max-h-[min(920px,94vh)] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-900 text-db-ink-0 shadow-xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <div>
            <div className="text-sm font-medium text-db-ink-0">
              {t("config.map.modalTitle", { label: district.label || t("config.map.untitledDistrict") })}
            </div>
            <p className="mt-1 text-xs text-db-ink-100/70">
              {drawing
                ? t("config.map.drawingHint")
                : hasBounds
                  ? t("config.map.moveResizeHint")
                  : t("config.map.drawHint")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!drawing ? (
              <AdminButton
                variant="secondary"
                size="sm"
                onClick={() => setDrawing(true)}
              >
                {hasBounds ? t("config.map.redraw") : t("config.map.drawArea")}
              </AdminButton>
            ) : (
              <AdminButton
                variant="secondary"
                size="sm"
                onClick={() => setDrawing(false)}
              >
                {t("config.map.cancelDrawing")}
              </AdminButton>
            )}
            <AdminButton
              variant="secondary"
              size="sm"
              disabled={!hasBounds}
              onClick={() => {
                setDrawing(false)
                onChangeBounds(null)
              }}
            >
              {t("config.map.clear")}
            </AdminButton>
            <AdminButton variant="accent" size="sm" onClick={onClose}>
              {t("common.done")}
            </AdminButton>
          </div>
        </div>
        <div className="min-h-0 flex-1 p-4">
          <div
            ref={containerRef}
            className="h-[min(640px,70vh)] w-full overflow-hidden rounded border border-[color:var(--border-hairline)]"
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}
