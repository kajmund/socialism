/**
 * Env validation. Required vars fail fast at boot.
 * Admin surfaces call the API via VITE_API_BASE_URL.
 */
function required(name: string): string {
  const value = import.meta.env[name]
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Missing required env var: ${name}`)
  }
  return value
}

export const env = {
  apiBaseUrl: required("VITE_API_BASE_URL"),
  supabaseUrl: required("VITE_SUPABASE_URL"),
  supabaseAnonKey: required("VITE_SUPABASE_ANON_KEY"),
}
