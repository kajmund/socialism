import { forwardRef, useImperativeHandle, useRef } from "react"
import { useLocale } from "@/i18n"
import { scrollReportCanvas } from "@/lib/spindoctorRefs"

export type ReportCanvasHandle = {
  scrollToSection: (sectionId: string) => void
}

type ReportCanvasProps = {
  html: string
  title?: string
}

export const ReportCanvas = forwardRef<ReportCanvasHandle, ReportCanvasProps>(
  function ReportCanvas({ html, title }, ref) {
    const { t } = useLocale()
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    useImperativeHandle(ref, () => ({
      scrollToSection(sectionId: string) {
        scrollReportCanvas(iframeRef.current, sectionId)
      },
    }))

    return (
      <div className="spinndoctor-canvas">
        <iframe
          ref={iframeRef}
          title={title || t("reports.iframeTitle")}
          srcDoc={html}
          className="spinndoctor-canvas-frame"
          sandbox="allow-same-origin allow-scripts allow-popups"
        />
      </div>
    )
  },
)
