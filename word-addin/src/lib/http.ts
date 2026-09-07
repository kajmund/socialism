export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(message: string, options: { status?: number; body?: unknown } = {}) {
    super(message)
    this.name = "ApiError"
    this.status = options.status ?? 0
    this.body = options.body ?? null
  }
}

export async function httpRequest<T>(
  url: string,
  options: {
    method?: string
    body?: unknown
    token: string
  },
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${options.token}`,
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json"
  }
  let response: Response
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError("Network request failed")
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
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : response.statusText
    throw new ApiError(detail || `HTTP ${response.status}`, {
      status: response.status,
      body: parsed,
    })
  }
  return parsed as T
}
