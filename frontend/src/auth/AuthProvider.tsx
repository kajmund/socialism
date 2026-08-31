import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { listKunder, type Kund } from "@/api/kunder"
import {
  authAdapter,
  canAccessConfiguration,
  type AuthSession,
  type AuthUser,
  type Role,
} from "@/lib/auth"

type AuthContextValue = {
  session: AuthSession | null
  user: AuthUser | null
  role: Role | null
  loading: boolean
  isAdmin: boolean
  isBolag: boolean
  resolvedModules: string[]
  hasModule: (moduleId: string) => boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

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

async function resolveModules(user: AuthUser): Promise<string[]> {
  try {
    const kunder = await listKunder()
    if (user.kundSlug === null) {
      return uniqueModuleIds(kunder)
    }
    const kund = kunder.find((row) => row.slug === user.kundSlug)
    if (!kund) {
      console.warn(
        `No kund with slug "${user.kundSlug}"; using static session modules`,
      )
      return user.modules
    }
    return kund.available_modules
  } catch (err) {
    console.warn("Failed to load kund modules; using static session modules", err)
    return user.modules
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [resolvedModules, setResolvedModules] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const next = await authAdapter.getSession()
      if (cancelled) return
      if (!next) {
        setResolvedModules([])
        setSession(null)
        setLoading(false)
        return
      }
      const modules = await resolveModules(next.user)
      if (cancelled) return
      setResolvedModules(modules)
      setSession(next)
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const next = await authAdapter.signIn(username, password)
    const modules = await resolveModules(next.user)
    setResolvedModules(modules)
    setSession(next)
  }, [])

  const signOut = useCallback(async () => {
    await authAdapter.signOut()
    setResolvedModules([])
    setSession(null)
  }, [])

  const value = useMemo<AuthContextValue>(() => {
    const role = session?.user.role ?? null
    const user = session?.user ?? null
    return {
      session,
      user,
      role,
      loading,
      isAdmin: role != null && canAccessConfiguration(role),
      isBolag: role === "bolag",
      resolvedModules,
      hasModule: (moduleId: string) => resolvedModules.includes(moduleId),
      signIn,
      signOut,
    }
  }, [loading, resolvedModules, session, signIn, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
