import { useEffect, useMemo, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { listPersonas } from "@/api/personas"
import { personaInitials } from "@/data/library"
import type { LibraryPersona } from "@/data/library-types"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type AddFromLibraryPanelProps = {
  excludeNames?: string[]
  excludeIds?: string[]
  onAdd: (persona: LibraryPersona) => void
  hint?: string
}

export function AddFromLibraryPanel({
  excludeNames = [],
  excludeIds = [],
  onAdd,
  hint,
}: AddFromLibraryPanelProps) {
  const { t } = useLocale()
  const [query, setQuery] = useState("")
  const [personas, setPersonas] = useState<LibraryPersona[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listPersonas()
      .then((data) => {
        if (!cancelled) {
          setPersonas(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("populations.libPanel.loadError"))
        }
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const excludeNameSet = useMemo(
    () => new Set(excludeNames.map((n) => n.toLowerCase())),
    [excludeNames],
  )
  const excludeIdSet = useMemo(() => new Set(excludeIds), [excludeIds])

  const list = useMemo(() => {
    const ql = query.toLowerCase()
    return personas.filter((p) => {
      if (excludeIdSet.has(p.id)) return false
      if (excludeNameSet.has(p.name.toLowerCase())) return false
      if (!ql) return true
      return (
        p.name.toLowerCase().includes(ql) ||
        p.district.toLowerCase().includes(ql) ||
        p.occ.toLowerCase().includes(ql)
      )
    })
  }, [personas, excludeNameSet, excludeIdSet, query])

  function originLabel(origin: LibraryPersona["origin"]): string {
    switch (origin) {
      case "manuell":
        return t("populations.libPanel.originManual")
      case "beskrivning":
        return t("populations.libPanel.originDescription")
      case "demografi":
        return t("populations.libPanel.originDemographic")
      case "population":
        return t("populations.libPanel.originPopulation")
      default: {
        const exhaustive: never = origin
        return exhaustive
      }
    }
  }

  return (
    <Card className="add-lib-panel mb-5 gap-0 py-5 ring-1 ring-border">
      <CardContent className="px-5">
        <div className="add-lib-hint">{hint ?? t("populations.libPanel.defaultHint")}</div>
        {error && <div className="add-lib-empty">{error}</div>}
        <input
          className="dsearch add-lib-search"
          placeholder={t("populations.libPanel.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="add-lib-list">
          {list.length ? (
            list.map((p) => (
              <div className="add-lib-row" key={p.id}>
                <div className="add-lib-who">
                  <div className="av">{personaInitials(p.name)}</div>
                  <div className="add-lib-meta">
                    <div className="nm">
                      {p.name}
                      <span className="origin">{originLabel(p.origin)}</span>
                    </div>
                    <div className="sub">
                      {p.age} · {p.occ} · {p.district}
                      {p.pops.length > 0
                        ? t("populations.libPanel.alreadyIn", { count: p.pops.length })
                        : t("populations.libPanel.unassigned")}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="add-lib-btn"
                  onClick={() => onAdd(p)}
                >
                  {t("populations.libPanel.add")}
                </button>
              </div>
            ))
          ) : (
            <div className="add-lib-empty">
              {query
                ? t("populations.libPanel.noMatches", { query })
                : t("populations.libPanel.allAlreadyHere")}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
