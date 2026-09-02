/**
 * Auth boundary — Supabase magic-link adapter.
 * Keep this module as the only import surface for session + token.
 */

import { homePathForModules } from "@/lib/moduleHomePaths"
import { supabase } from "@/lib/supabaseClient"

export type Role = "admin" | "user" | "bolag"

export type AuthUser = {
  id: string
  username: string
  email: string
  role: Role
  modules: string[]
  kundSlug: string | null
}

export type AuthSession = {
  user: AuthUser
  accessToken: string | null
}

export type AuthAdapter = {
  requestMagicLink(email: string): Promise<void>
  signOut(): Promise<void>
  getSession(): Promise<AuthSession | null>
  getAccessToken(): Promise<string | null>
  onSessionChange(cb: (session: AuthSession | null) => void): () => void
}

export class MagicLinkError extends Error {
  constructor(message = "magic_link_failed") {
    super(message)
    this.name = "MagicLinkError"
  }
}

function sessionFromSupabase(
  accessToken: string,
  user: { id: string; email?: string | null },
): AuthSession {
  const email = (user.email ?? "").trim() || user.id
  return {
    accessToken,
    user: {
      id: user.id,
      username: email,
      email,
      // Role/modules filled by AuthProvider via GET /me.
      role: "user",
      modules: [],
      kundSlug: null,
    },
  }
}

const supabaseAuthAdapter: AuthAdapter = {
  async requestMagicLink(email) {
    const trimmed = email.trim()
    const { error } = await supabase.auth.signInWithOtp({
      email: trimmed,
      options: {
        emailRedirectTo: `${window.location.origin}/login`,
        shouldCreateUser: false,
      },
    })
    if (error) throw new MagicLinkError(error.message)
  },

  async signOut() {
    await supabase.auth.signOut()
  },

  async getSession() {
    const { data, error } = await supabase.auth.getSession()
    if (error || !data.session?.user) return null
    return sessionFromSupabase(data.session.access_token, data.session.user)
  },

  async getAccessToken() {
    const { data } = await supabase.auth.getSession()
    return data.session?.access_token ?? null
  },

  onSessionChange(cb) {
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session?.user) {
        cb(null)
        return
      }
      cb(sessionFromSupabase(session.access_token, session.user))
    })
    return () => {
      data.subscription.unsubscribe()
    }
  },
}

export const authAdapter: AuthAdapter = supabaseAuthAdapter

export function canAccessConfiguration(role: Role): boolean {
  return role === "admin"
}

export function hasModule(user: AuthUser | null | undefined, moduleId: string): boolean {
  if (!user) return false
  return user.modules.includes(moduleId)
}

export function homePathForUser(modules: readonly string[]): string {
  return homePathForModules(modules) ?? "/login"
}
