export function holdProgrammaticScroll(
  viewport: HTMLElement,
  flag: { current: boolean },
  cancel: { current: (() => void) | null },
) {
  cancel.current?.()
  flag.current = true
  let timer = 0
  const done = () => {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      flag.current = false
      viewport.removeEventListener("scroll", done)
      if (cancel.current === stop) cancel.current = null
    }, 120)
  }
  const stop = () => {
    window.clearTimeout(timer)
    flag.current = false
    viewport.removeEventListener("scroll", done)
  }
  cancel.current = stop
  viewport.addEventListener("scroll", done)
  done()
}

export function markerOutsideViewport(
  marker: { top: number; bottom: number },
  viewport: { top: number; bottom: number },
  margin = 24,
): boolean {
  return marker.bottom < viewport.top + margin || marker.top > viewport.bottom - margin
}

export function pageAtViewportTop(
  pages: readonly { page: number; top: number; bottom: number }[],
  viewportTop: number,
): number | null {
  const line = viewportTop + 8
  for (const page of pages) {
    if (page.bottom > line) return page.page
  }
  return pages.length > 0 ? pages[pages.length - 1].page : null
}
