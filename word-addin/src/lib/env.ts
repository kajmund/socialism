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
  return url.toString().replace(/\/$/, "")
}

const useDevProxy = import.meta.env.VITE_DEV_PROXY === "true"
const configuredApiBaseUrl = required("VITE_API_BASE_URL")
const apiBaseUrl = useDevProxy ? window.location.origin : configuredApiBaseUrl

export const env = {
  apiBaseUrl,
  wsBaseUrl: wsBaseFromHttp(apiBaseUrl),
}
