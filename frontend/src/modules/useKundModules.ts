import { useEffect, useMemo, useState } from "react"
import { listKunder, type Kund } from "@/api/kunder"
import { useAuth } from "@/auth/AuthProvider"
import { ApiError } from "@/lib/api"
import type { CustomerScope } from "@/lib/scoping"
import type { ModuleManifest } from "@/modules/manifest"
import { kunderForScope, uniqueModuleIds } from "@/modules/kundModules"
import { manifestsForIds } from "@/modules/moduleRegistry"

export function useKundModules(scope?: CustomerScope): {
  loading: boolean
  error: string | null
  kunder: Kund[]
  allKunder: Kund[]
  moduleIds: string[]
  manifests: ModuleManifest[]
} {
  const { role } = useAuth()
  const [allKunder, setAllKunder] = useState<Kund[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listKunder()
      .then((rows) => {
        if (cancelled) return
        setAllKunder(rows)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "load_error")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const kunder = useMemo(
    () => kunderForScope(allKunder, role, scope),
    [allKunder, role, scope],
  )
  const moduleIds = useMemo(() => uniqueModuleIds(kunder), [kunder])
  const manifests = useMemo(() => manifestsForIds(moduleIds), [moduleIds])

  return { loading, error, kunder, allKunder, moduleIds, manifests }
}
