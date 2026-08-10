import { useMemo } from "react"
import { useLocation, useParams, useSearchParams } from "react-router-dom"
import { useLocale, type MessageKey } from "@/i18n"

export type HelpViewContext = {
  path: string
  view_key: string
  label: string
  params: Record<string, string>
  search: Record<string, string>
}

type ViewMatch = {
  test: (path: string) => boolean
  key: MessageKey
  viewKey: string
}

const VIEW_MATCHES: ViewMatch[] = [
  { test: (p) => p === "/", key: "help.views.dashboard", viewKey: "dashboard" },
  { test: (p) => p === "/runs", key: "help.views.runsList", viewKey: "runs.list" },
  { test: (p) => p === "/runs/new", key: "help.views.runsNew", viewKey: "runs.new" },
  {
    test: (p) => /^\/runs\/[^/]+\/edit$/.test(p),
    key: "help.views.runsEdit",
    viewKey: "runs.edit",
  },
  { test: (p) => p === "/personas", key: "help.views.personasList", viewKey: "personas.list" },
  { test: (p) => p === "/personas/new", key: "help.views.personasNew", viewKey: "personas.new" },
  {
    test: (p) => /^\/personas\/[^/]+$/.test(p) && p !== "/personas/new",
    key: "help.views.personasDetail",
    viewKey: "personas.detail",
  },
  {
    test: (p) => p === "/populations",
    key: "help.views.populationsList",
    viewKey: "populations.list",
  },
  {
    test: (p) => p === "/populations/new",
    key: "help.views.populationsNew",
    viewKey: "populations.new",
  },
  {
    test: (p) => /^\/populations\/[^/]+\/edit$/.test(p),
    key: "help.views.populationsEdit",
    viewKey: "populations.edit",
  },
  {
    test: (p) => /^\/populations\/[^/]+$/.test(p) && !p.endsWith("/new") && !p.endsWith("/edit"),
    key: "help.views.populationsDetail",
    viewKey: "populations.detail",
  },
  { test: (p) => p === "/messages", key: "help.views.messagesList", viewKey: "messages.list" },
  { test: (p) => p === "/messages/new", key: "help.views.messagesNew", viewKey: "messages.new" },
  {
    test: (p) => /^\/messages\/[^/]+\/edit$/.test(p),
    key: "help.views.messagesEdit",
    viewKey: "messages.edit",
  },
  {
    test: (p) => p === "/tools/configurations" || p === "/configurations",
    key: "help.views.configurationsList",
    viewKey: "tools.configurations",
  },
  {
    test: (p) => p === "/tools/configurations/new",
    key: "help.views.configurationsNew",
    viewKey: "tools.configurations.new",
  },
  {
    test: (p) => /^\/tools\/configurations\/[^/]+\/edit$/.test(p),
    key: "help.views.configurationsEdit",
    viewKey: "tools.configurations.edit",
  },
  {
    test: (p) => p === "/tools/anchor-sets",
    key: "help.views.anchorSetsList",
    viewKey: "tools.anchor_sets",
  },
  {
    test: (p) => p === "/tools/anchor-sets/new",
    key: "help.views.anchorSetsNew",
    viewKey: "tools.anchor_sets.new",
  },
  {
    test: (p) => /^\/tools\/anchor-sets\/[^/]+\/edit$/.test(p),
    key: "help.views.anchorSetsEdit",
    viewKey: "tools.anchor_sets.edit",
  },
  {
    test: (p) => p === "/tools/playground" || p === "/playground",
    key: "help.views.playground",
    viewKey: "tools.playground",
  },
  {
    test: (p) => p === "/tools/cache",
    key: "help.views.embeddingCache",
    viewKey: "tools.cache",
  },
  { test: (p) => p === "/tools", key: "help.views.tools", viewKey: "tools.home" },
  { test: (p) => p === "/jobs", key: "help.views.jobs", viewKey: "jobs.list" },
  {
    test: (p) => /^\/reports\/[^/]+$/.test(p),
    key: "help.views.report",
    viewKey: "reports.view",
  },
]

function resolveView(pathname: string, t: (key: MessageKey) => string): Pick<HelpViewContext, "view_key" | "label"> {
  for (const match of VIEW_MATCHES) {
    if (match.test(pathname)) {
      return { view_key: match.viewKey, label: t(match.key) }
    }
  }
  return { view_key: "unknown", label: t("help.views.unknown") }
}

export function useHelpView(): HelpViewContext {
  const { pathname } = useLocation()
  const params = useParams()
  const [searchParams] = useSearchParams()
  const { t } = useLocale()

  return useMemo(() => {
    const paramRecord: Record<string, string> = {}
    for (const [key, value] of Object.entries(params)) {
      if (value != null && value !== "") paramRecord[key] = value
    }
    const search: Record<string, string> = {}
    searchParams.forEach((value, key) => {
      if (value !== "") search[key] = value
    })
    const tab = search.tab
    const resolved = resolveView(pathname, t)
    const label =
      tab && (pathname.includes("/runs/") || pathname.includes("/edit"))
        ? `${resolved.label} (${tab})`
        : resolved.label
    return {
      path: pathname,
      view_key: resolved.view_key,
      label,
      params: paramRecord,
      search,
    }
  }, [params, pathname, searchParams, t])
}

export function helpViewKey(view: HelpViewContext): string {
  return [view.path, view.view_key, JSON.stringify(view.params), JSON.stringify(view.search)].join("|")
}
