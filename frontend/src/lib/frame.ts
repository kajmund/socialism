export function isSameOriginFrame(): boolean {
  if (window.self === window.top) return false
  try {
    return window.parent.location.origin === window.location.origin
  } catch {
    return false
  }
}
