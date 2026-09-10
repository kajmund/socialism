import type { ExecutionRun } from "@/api/execution"
import { caseIdFromContext } from "@/components/execution/panelConfig"
import { formatWhen } from "@/components/execution/format"
import { useLocale, type MessageKey } from "@/i18n"

function moduleLabel(module: string, t: (key: MessageKey) => string): string {
  switch (module) {
    case "dd":
      return t("modules.dd.name")
    case "politik":
      return t("modules.politik.name")
    case "expertgranskning":
      return t("modules.expertgranskning.name")
    case "rattsunderlag":
      return t("modules.rattsunderlag.name")
    default:
      return module
  }
}

export function RunHeader({ run }: { run: ExecutionRun }) {
  const { t, intl } = useLocale()
  const emDash = t("common.emDash")
  const caseId = caseIdFromContext(run.context)
  return (
    <div className="head-row">
      <div style={{ minWidth: 0, flex: 1 }}>
        <h1
          style={{
            font: "var(--text-h1)",
            fontFamily: "'Bai Jamjuree', sans-serif",
            fontWeight: 400,
            margin: 0,
          }}
        >
          {run.title}
        </h1>
        <p className="mt-2 text-sm text-[color:var(--text-muted)]">
          {t("execution.run.module")}: {moduleLabel(run.module, t)}
          {caseId ? ` · ${t("execution.run.caseId", { id: caseId })}` : null}
        </p>
        <p className="mt-1 text-xs text-[color:var(--text-muted)]">
          {t("execution.run.created", { when: formatWhen(run.created_at, intl, emDash) })}
          {" · "}
          {t("execution.run.updated", { when: formatWhen(run.updated_at, intl, emDash) })}
        </p>
      </div>
    </div>
  )
}
