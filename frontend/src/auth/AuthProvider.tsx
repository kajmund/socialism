import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { api } from "@/lib/api"
import {
  authAdapter,
  canAccessConfiguration,
  type AuthSession,
  type AuthUser,
  type Role,
} from "@/lib/auth"

type MeResponse = {
  id: string
  email: string
  role: Role
  kund_id: number | null
  kund_slug: string | null
  available_modules: string[]
}

type AuthContextValue = {
  session: AuthSession | null
  user: AuthUser | null
  role: Role | null
  loading: boolean
  isAdmin: boolean
  isBolag: boolean
  resolvedModules: string[]
  hasModule: (moduleId: string) => boolean
  requestMagicLink: (email: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function hydrateFromMe(base: AuthSession): Promise<AuthSession> {
  const me = await api.get<MeResponse>("/me")
  return {
    accessToken: base.accessToken,
    user: {
      id: me.id,
      username: me.email,
      email: me.email,
      role: me.role,
      modules: me.available_modules,
      kundSlug: me.kund_slug,
    },
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [resolvedModules, setResolvedModules] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const applySession = useCallback(async (next: AuthSession | null) => {
    if (!next) {
      setResolvedModules([])
      setSession(null)
      return
    }
    const hydrated = await hydrateFromMe(next)
    setResolvedModules(hydrated.user.modules)
    setSession(hydrated)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const next = await authAdapter.getSession()
        if (cancelled) return
        await applySession(next)
      } catch {
        if (!cancelled) {
          setResolvedModules([])
          setSession(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    const unsubscribe = authAdapter.onSessionChange((next) => {
      void (async () => {
        try {
          await applySession(next)
        } catch {
          setResolvedModules([])
          setSession(null)
        } finally {
          setLoading(false)
        }
      })()
    })

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [applySession])

  const requestMagicLink = useCallback(async (email: string) => {
    await authAdapter.requestMagicLink(email)
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
      requestMagicLink,
      signOut,
    }
  }, [loading, resolvedModules, session, requestMagicLink, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
