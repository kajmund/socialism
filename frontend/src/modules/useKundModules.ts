import { useEffect, useMemo, useState } from "react"
import { listKunder, type Kund } from "@/api/kunder"
import { useAuth } from "@/auth/AuthProvider"
import { ApiError } from "@/lib/api"
import type { Role } from "@/lib/auth"
import { BOLAG_DEMO_CUSTOMER_SLUG, OS_CUSTOMER_SLUG } from "@/lib/scoping"
import type { ModuleManifest } from "@/modules/manifest"
import { manifestsForIds } from "@/modules/moduleRegistry"

function kunderForRole(kunder: Kund[], role: Role | null): Kund[] {
  if (role === "bolag") {
    return kunder.filter((row) => row.slug === BOLAG_DEMO_CUSTOMER_SLUG)
  }
  if (role === "admin") return kunder
  return kunder.filter((row) => row.slug === OS_CUSTOMER_SLUG)
}

function uniqueModuleIds(kunder: Kund[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const kund of kunder) {
    for (const id of kund.available_modules) {
      if (seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
  }
  return out
}

export function useKundModules(): {
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

  const kunder = useMemo(() => kunderForRole(allKunder, role), [allKunder, role])
  const moduleIds = useMemo(() => uniqueModuleIds(kunder), [kunder])
  const manifests = useMemo(() => manifestsForIds(moduleIds), [moduleIds])

  return { loading, error, kunder, allKunder, moduleIds, manifests }
}
