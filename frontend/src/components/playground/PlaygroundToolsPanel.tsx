import { useEffect, useMemo, useState } from "react"
import {
  getPlaygroundToolsCatalog,
  runPlaygroundTool,
  type ToolCatalogFamily,
  type ToolCatalogTool,
  type ToolRunResponse,
} from "@/api/playground"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

function defaultArgsFor(tool: ToolCatalogTool): Record<string, string> {
  const props = tool.parameters.properties ?? {}
  const out: Record<string, string> = {}
  for (const key of Object.keys(props)) {
    out[key] = ""
  }
  return out
}

export function PlaygroundToolsPanel() {
  const { t } = useLocale()
  const [families, setFamilies] = useState<ToolCatalogFamily[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [familyId, setFamilyId] = useState<string>("web_search")
  const [toolName, setToolName] = useState("")
  const [argValues, setArgValues] = useState<Record<string, string>>({})
  const [result, setResult] = useState<ToolRunResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const catalog = await getPlaygroundToolsCatalog()
        if (cancelled) return
        setFamilies(catalog.families)
        const firstFamily = catalog.families[0]
        const firstTool = firstFamily?.tools[0]
        if (firstFamily) setFamilyId(firstFamily.id)
        if (firstTool) {
          setToolName(firstTool.name)
          setArgValues(defaultArgsFor(firstTool))
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const activeFamily = useMemo(
    () => families.find((f) => f.id === familyId) ?? null,
    [families, familyId],
  )

  const activeTool = useMemo(
    () => activeFamily?.tools.find((tool) => tool.name === toolName) ?? null,
    [activeFamily, toolName],
  )

  function onFamilyChange(next: string) {
    setFamilyId(next)
    setResult(null)
    setError(null)
    const family = families.find((f) => f.id === next)
    const tool = family?.tools[0]
    if (tool) {
      setToolName(tool.name)
      setArgValues(defaultArgsFor(tool))
    } else {
      setToolName("")
      setArgValues({})
    }
  }

  function onToolChange(next: string) {
    setToolName(next)
    setResult(null)
    setError(null)
    const tool = activeFamily?.tools.find((item) => item.name === next)
    if (tool) setArgValues(defaultArgsFor(tool))
  }

  async function onRun() {
    if (!activeTool) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const argumentsPayload: Record<string, unknown> = {}
      for (const [key, raw] of Object.entries(argValues)) {
        const trimmed = raw.trim()
        if (!trimmed) continue
        const schemaType = activeTool.parameters.properties?.[key]?.type
        if (schemaType === "integer" || schemaType === "number") {
          const n = Number(trimmed)
          if (Number.isNaN(n)) {
            setError(t("playground.tools.badNumber", { key }))
            setBusy(false)
            return
          }
          argumentsPayload[key] = schemaType === "integer" ? Math.trunc(n) : n
        } else {
          argumentsPayload[key] = trimmed
        }
      }
      const out = await runPlaygroundTool({
        tool_name: activeTool.name,
        arguments: argumentsPayload,
      })
      setResult(out)
    } catch (err) {
      setError(t("playground.error", { message: errorMessage(err) }))
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t("playground.tools.loading")}</p>
  }

  return (
    <section
      id="playground-panel-tools"
      role="tabpanel"
      aria-labelledby="playground-tab-tools"
      className="space-y-6"
    >
      <p className="text-sm text-muted-foreground">{t("playground.tools.intro")}</p>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-4">
        <label className="grid gap-1 text-sm">
          <span>{t("playground.tools.family")}</span>
          <select
            className="min-w-[12rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={familyId}
            onChange={(e) => onFamilyChange(e.target.value)}
          >
            {families.map((family) => (
              <option key={family.id} value={family.id}>
                {family.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span>{t("playground.tools.tool")}</span>
          <select
            className="min-w-[16rem] rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5"
            value={toolName}
            onChange={(e) => onToolChange(e.target.value)}
            disabled={!activeFamily || activeFamily.tools.length === 0}
          >
            {(activeFamily?.tools ?? []).map((tool) => (
              <option key={tool.name} value={tool.name}>
                {tool.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {activeFamily?.unavailable_reason ? (
        <p className="text-sm text-amber-400">
          {t("playground.tools.unavailable", { reason: activeFamily.unavailable_reason })}
        </p>
      ) : null}

      {activeTool ? (
        <div className="space-y-3">
          {activeTool.description ? (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-[color:var(--border-hairline)] bg-black/20 p-3 text-xs text-muted-foreground">
              {activeTool.description}
            </pre>
          ) : null}
          <div className="space-y-2">
            <h3 className="text-sm font-medium">{t("playground.tools.args")}</h3>
            {Object.keys(activeTool.parameters.properties ?? {}).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("playground.tools.noArgs")}</p>
            ) : (
              Object.entries(activeTool.parameters.properties ?? {}).map(([key, schema]) => (
                <label key={key} className="grid gap-1 text-sm">
                  <span className="font-mono text-xs">
                    {key}
                    {(activeTool.parameters.required ?? []).includes(key)
                      ? ` (${t("playground.tools.required")})`
                      : ""}
                  </span>
                  {schema.description ? (
                    <span className="text-xs text-muted-foreground">{schema.description}</span>
                  ) : null}
                  <input
                    className="w-full rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 font-mono text-xs"
                    value={argValues[key] ?? ""}
                    onChange={(e) =>
                      setArgValues((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                  />
                </label>
              ))
            )}
          </div>
          <Button type="button" disabled={busy || !toolName} onClick={() => void onRun()}>
            {busy ? t("playground.running") : t("playground.tools.run")}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("playground.tools.emptyFamily")}</p>
      )}

      {result ? (
        <div className="space-y-2 rounded border border-[color:var(--border-hairline)] p-3">
          <div className="text-sm text-muted-foreground">
            {t("playground.tools.elapsed", { ms: String(result.elapsed_ms) })}
          </div>
          {result.error ? (
            <p className="text-sm text-destructive">{result.error}</p>
          ) : null}
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-black/20 p-3 text-xs">
            {JSON.stringify(
              {
                tool_name: result.tool_name,
                arguments: result.arguments,
                result: result.result,
                error: result.error,
              },
              null,
              2,
            )}
          </pre>
        </div>
      ) : null}
    </section>
  )
}
