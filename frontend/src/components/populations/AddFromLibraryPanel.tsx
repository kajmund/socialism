import { useEffect, useMemo, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { listPersonas } from "@/api/personas"
import { ORIGIN_LABEL, personaInitials } from "@/data/library"
import type { LibraryPersona } from "@/data/library-types"
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
  hint = "Sök i biblioteket och lägg till personas som saknas i populationen.",
}: AddFromLibraryPanelProps) {
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
          setError(err instanceof ApiError ? err.message : "Kunde inte hämta biblioteket")
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

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

  return (
    <Card className="add-lib-panel mb-5 gap-0 py-5 ring-1 ring-border">
      <CardContent className="px-5">
        <div className="add-lib-hint">{hint}</div>
        {error && <div className="add-lib-empty">{error}</div>}
        <input
          className="dsearch add-lib-search"
          placeholder="Sök namn, ort, yrke..."
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
                      <span className="origin">{ORIGIN_LABEL[p.origin]}</span>
                    </div>
                    <div className="sub">
                      {p.age} · {p.occ} · {p.district}
                      {p.pops.length > 0
                        ? ` · redan i ${p.pops.length} pop.`
                        : " · ofördelad"}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="add-lib-btn"
                  onClick={() => onAdd(p)}
                >
                  + Lägg till
                </button>
              </div>
            ))
          ) : (
            <div className="add-lib-empty">
              {query
                ? `Inga träffar för ”${query}”.`
                : "Alla personas i biblioteket finns redan här."}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
