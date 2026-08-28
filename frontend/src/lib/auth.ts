/**
 * Auth boundary. Phase 1 uses a static username/password adapter.
 * Swap `authAdapter` to a Supabase implementation when Auth is enabled —
 * keep this module as the only import surface for session + token.
 */

export type Role = "admin" | "user" | "bolag"

export type AuthUser = {
  id: string
  username: string
  email: string
  role: Role
  modules: string[]
}

export type AuthSession = {
  user: AuthUser
  accessToken: string | null
}

export type AuthAdapter = {
  signIn(username: string, password: string): Promise<AuthSession>
  signOut(): Promise<void>
  getSession(): Promise<AuthSession | null>
  getAccessToken(): Promise<string | null>
}

export class InvalidCredentialsError extends Error {
  constructor() {
    super("invalid_credentials")
    this.name = "InvalidCredentialsError"
  }
}

const STORAGE_KEY = "opinionssimulator.auth"

const STATIC_ACCOUNTS: ReadonlyArray<{
  username: string
  password: string
  user: AuthUser
}> = [
  {
    username: "admin",
    password: "admin",
    user: {
      id: "static-admin",
      username: "admin",
      email: "admin@local",
      role: "admin",
      modules: ["politik", "dd"],
    },
  },
  {
    username: "user",
    password: "user",
    user: {
      id: "static-user",
      username: "user",
      email: "user@local",
      role: "user",
      modules: ["politik"],
    },
  },
  {
    username: "bolag",
    password: "bolag",
    user: {
      id: "static-bolag",
      username: "bolag",
      email: "bolag@local",
      role: "bolag",
      modules: ["dd"],
    },
  },
]

function isRole(value: unknown): value is Role {
  return value === "admin" || value === "user" || value === "bolag"
}

function parseModules(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string")
}

function parseSession(raw: string): AuthSession | null {
  const parsed: unknown = JSON.parse(raw)
  if (parsed == null || typeof parsed !== "object") return null
  const record = parsed as Record<string, unknown>
  const user = record.user
  if (user == null || typeof user !== "object") return null
  const fields = user as Record<string, unknown>
  if (
    typeof fields.id !== "string" ||
    typeof fields.username !== "string" ||
    typeof fields.email !== "string" ||
    !isRole(fields.role)
  ) {
    return null
  }
  const accessToken = record.accessToken
  if (accessToken !== null && typeof accessToken !== "string") return null
  return {
    user: {
      id: fields.id,
      username: fields.username,
      email: fields.email,
      role: fields.role,
      modules: parseModules(fields.modules),
    },
    accessToken,
  }
}

function readStoredSession(): AuthSession | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return parseSession(raw)
  } catch {
    localStorage.removeItem(STORAGE_KEY)
    return null
  }
}

const staticAuthAdapter: AuthAdapter = {
  async signIn(username, password) {
    const match = STATIC_ACCOUNTS.find(
      (account) =>
        account.username.toLowerCase() === username.trim().toLowerCase() &&
        account.password === password,
    )
    if (!match) throw new InvalidCredentialsError()
    const session: AuthSession = { user: match.user, accessToken: null }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    return session
  },

  async signOut() {
    localStorage.removeItem(STORAGE_KEY)
  },

  async getSession() {
    return readStoredSession()
  },

  async getAccessToken() {
    return readStoredSession()?.accessToken ?? null
  },
}

/** Replace this assignment with a Supabase adapter when Auth is enabled. */
export const authAdapter: AuthAdapter = staticAuthAdapter

export function canAccessConfiguration(role: Role): boolean {
  return role === "admin"
}

export function hasModule(user: AuthUser | null | undefined, moduleId: string): boolean {
  if (!user) return false
  return user.modules.includes(moduleId)
}

export function homePathForRole(role: Role | null): string {
  if (role === "bolag") return "/bolag"
  return "/"
}
