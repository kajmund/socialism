const REF_PATTERN = /\[\[ref:([a-z0-9_-]+)\]\]/gi

/** Strip Spinndoktor section markers from assistant text shown in the thread. */
export function stripSpindoctorRefs(text: string): string {
  return text.replace(REF_PATTERN, "").trim()
}

/** Last [[ref:id]] in a reply, if any. */
export function lastSpindoctorRef(text: string): string | null {
  const matches = [...text.matchAll(new RegExp(REF_PATTERN.source, "gi"))]
  if (matches.length === 0) return null
  return matches[matches.length - 1][1] ?? null
}

export function scrollReportCanvas(
  iframe: HTMLIFrameElement | null,
  sectionId: string,
): void {
  if (!iframe?.contentWindow) return
  iframe.contentWindow.postMessage(
    { type: "spinndoctor-scroll", id: sectionId },
    "*",
  )
}
