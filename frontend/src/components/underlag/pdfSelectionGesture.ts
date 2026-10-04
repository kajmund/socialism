export function pdfSelectionGesture({ button, started, moved, clickCount, shiftKey }: {
  button: number
  started: boolean
  moved: boolean
  clickCount: number
  shiftKey: boolean
}): "ignore" | "select" | "clear" {
  if (button !== 0 || !started) return "ignore"
  return moved || clickCount > 1 || shiftKey ? "select" : "clear"
}
