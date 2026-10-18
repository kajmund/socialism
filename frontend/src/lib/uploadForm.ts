import { ApiError, errorDetail } from "@/lib/http"

export function uploadForm<T>(
  url: string,
  form: FormData,
  options: { token?: string | null; timeoutMs?: number; onProgress?: (percent: number) => void } = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? 30_000
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const timer = window.setTimeout(() => {
      xhr.abort()
      reject(new ApiError("Request timed out", { isNetworkError: true }))
    }, timeoutMs)
    xhr.open("POST", url)
    xhr.setRequestHeader("Accept", "application/json")
    if (options.token) xhr.setRequestHeader("Authorization", `Bearer ${options.token}`)
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !options.onProgress) return
      const percent = Math.min(99, Math.floor((event.loaded * 100) / event.total))
      options.onProgress(percent)
    }
    xhr.onload = () => {
      window.clearTimeout(timer)
      const parsed = parseBody(xhr.responseText)
      if (xhr.status === 204) {
        resolve(undefined as T)
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(errorDetail(parsed, xhr.status), { status: xhr.status, body: parsed }))
        return
      }
      resolve(parsed as T)
    }
    xhr.onerror = () => {
      window.clearTimeout(timer)
      reject(new ApiError("Network request failed", { isNetworkError: true }))
    }
    xhr.send(form)
  })
}

function parseBody(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}
