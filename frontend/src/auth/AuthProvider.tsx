import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import {
  authAdapter,
  canAccessConfiguration,
  hasModule,
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
  hasModule: (moduleId: string) => boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void authAdapter.getSession().then((next) => {
      if (cancelled) return
      setSession(next)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const next = await authAdapter.signIn(username, password)
    setSession(next)
  }, [])

  const signOut = useCallback(async () => {
    await authAdapter.signOut()
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
      hasModule: (moduleId: string) => hasModule(user, moduleId),
      signIn,
      signOut,
    }
  }, [loading, session, signIn, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
