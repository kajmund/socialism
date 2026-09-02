import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"
import { ApiError, httpRequest, type HttpRequestOptions } from "@/lib/http"

export { ApiError }

type Query = Record<string, string | number | boolean | undefined | null>

async function accessToken(): Promise<string | null> {
  return authAdapter.getAccessToken()
}

function buildUrl(path: string, query?: Query): string {
  const base = env.apiBaseUrl.replace(/\/$/, "")
  const url = new URL(path.startsWith("/") ? path : `/${path}`, `${base}/`)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function call<T>(
  path: string,
  options: Omit<HttpRequestOptions, "token"> & { query?: Query } = {},
): Promise<T> {
  const { query, ...rest } = options
  const token = await accessToken()
  return httpRequest<T>(buildUrl(path, query), { ...rest, token })
}

export const api = {
  get<T>(path: string, query?: Query): Promise<T> {
    return call<T>(path, { method: "GET", query })
  },
  post<T>(
    path: string,
    body?: unknown,
    options?: Pick<HttpRequestOptions, "timeoutMs" | "jsonBody">,
  ): Promise<T> {
    return call<T>(path, { method: "POST", body, ...options })
  },
  postForm<T>(
    path: string,
    form: FormData,
    options?: Pick<HttpRequestOptions, "timeoutMs">,
  ): Promise<T> {
    return call<T>(path, { method: "POST", body: form, jsonBody: false, ...options })
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return call<T>(path, { method: "PUT", body })
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return call<T>(path, { method: "PATCH", body })
  },
  delete<T = void>(path: string, query?: Query): Promise<T> {
    return call<T>(path, { method: "DELETE", query })
  },
  async getBlob(path: string): Promise<Blob> {
    const token = await accessToken()
    const headers: Record<string, string> = { Accept: "*/*" }
    if (token) headers.Authorization = `Bearer ${token}`
    const response = await fetch(buildUrl(path), { headers })
    if (!response.ok) {
      let detail = `HTTP ${response.status}`
      try {
        const body: unknown = await response.json()
        if (
          typeof body === "object" &&
          body !== null &&
          "detail" in body &&
          typeof (body as { detail: unknown }).detail === "string"
        ) {
          detail = (body as { detail: string }).detail
        }
      } catch {
        /* keep status text */
      }
      throw new ApiError(detail, { status: response.status })
    }
    return response.blob()
  },
}
