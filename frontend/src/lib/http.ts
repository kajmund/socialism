export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  readonly isNetworkError: boolean

  constructor(
    message: string,
    options: { status?: number; body?: unknown; isNetworkError?: boolean } = {},
  ) {
    super(message)
    this.name = "ApiError"
    this.status = options.status ?? 0
    this.body = options.body ?? null
    this.isNetworkError = options.isNetworkError ?? false
  }
}

export type HttpRequestOptions = {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  timeoutMs?: number
  token?: string | null
  jsonBody?: boolean
}

export function errorDetail(parsed: unknown, status: number): string {
  if (typeof parsed !== "object" || parsed === null || !("detail" in parsed)) return `HTTP ${status}`
  const detail = (parsed as { detail: unknown }).detail
  if (typeof detail === "string" && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first && typeof first === "object" && "type" in first && typeof first.type === "string") return first.type
  }
  return `HTTP ${status}`
}

export async function httpRequest<T>(
  url: string,
  options: HttpRequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    headers = {},
    signal,
    timeoutMs = 30_000,
    token,
  } = options

  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener("abort", () => controller.abort(), { once: true })
  }

  const reqHeaders: Record<string, string> = { Accept: "application/json", ...headers }
  const useJson = body !== undefined && options.jsonBody !== false && !(body instanceof FormData)
  if (useJson) reqHeaders["Content-Type"] = "application/json"
  if (token) reqHeaders.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: reqHeaders,
      body: body === undefined ? undefined : useJson ? JSON.stringify(body) : (body as BodyInit),
      signal: controller.signal,
    })
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError"
    throw new ApiError(aborted ? "Request timed out" : "Network request failed", {
      isNetworkError: true,
    })
  } finally {
    window.clearTimeout(timeout)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!response.ok) {
    throw new ApiError(errorDetail(parsed, response.status), { status: response.status, body: parsed })
  }

  return parsed as T
}
