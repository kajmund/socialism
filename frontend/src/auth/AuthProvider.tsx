import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { api, ApiError } from "@/lib/api"
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

type ProfileError = "not_provisioned" | "invalid_token" | "unknown"

type AuthContextValue = {
  session: AuthSession | null
  user: AuthUser | null
  role: Role | null
  loading: boolean
  isAdmin: boolean
  isBolag: boolean
  resolvedModules: string[]
  hasModule: (moduleId: string) => boolean
  /** Set when Supabase session exists but GET /me fails. */
  profileError: ProfileError | null
  requestMagicLink: (email: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function profileErrorFromUnknown(err: unknown): ProfileError {
  if (err instanceof ApiError) {
    if (err.status === 403) return "not_provisioned"
    if (err.status === 401) return "invalid_token"
  }
  return "unknown"
}

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
  const [profileError, setProfileError] = useState<ProfileError | null>(null)

  const applySession = useCallback(async (next: AuthSession | null) => {
    if (!next) {
      setResolvedModules([])
      setSession(null)
      setProfileError(null)
      return
    }
    try {
      const hydrated = await hydrateFromMe(next)
      setProfileError(null)
      setResolvedModules(hydrated.user.modules)
      setSession(hydrated)
    } catch (err) {
      setResolvedModules([])
      setSession(null)
      setProfileError(profileErrorFromUnknown(err))
      throw err
    }
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
          // profileError already set in applySession
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
    setProfileError(null)
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
      profileError,
      requestMagicLink,
      signOut,
    }
  }, [loading, profileError, resolvedModules, session, requestMagicLink, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
