export const REVIEW_ROW_HEIGHT = 72

export function visibleRowWindow(
  scrollTop: number,
  viewportHeight: number,
  rowCount: number,
  rowHeight = REVIEW_ROW_HEIGHT,
  overscan = 8,
): { start: number; end: number } {
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const visible = Math.ceil(viewportHeight / rowHeight) + overscan * 2
  const end = Math.min(rowCount, start + visible)
  return { start, end }
}
