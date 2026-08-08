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

function wsBaseFromHttp(apiBaseUrl: string): string {
  const url = new URL(apiBaseUrl)
  if (url.protocol === "https:") url.protocol = "wss:"
  else if (url.protocol === "http:") url.protocol = "ws:"
  else {
    throw new Error(`VITE_API_BASE_URL must be http(s); got ${url.protocol}`)
  }
  // Strip trailing slash so callers can append `/ws/...`
  return url.toString().replace(/\/$/, "")
}

const apiBaseUrl = required("VITE_API_BASE_URL")

export const env = {
  apiBaseUrl,
  wsBaseUrl: wsBaseFromHttp(apiBaseUrl),
  supabaseUrl: required("VITE_SUPABASE_URL"),
  supabaseAnonKey: required("VITE_SUPABASE_ANON_KEY"),
}
