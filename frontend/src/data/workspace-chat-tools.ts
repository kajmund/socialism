export const WORKSPACE_CHAT_TOOLS = [
  "get_workspace_context",
  "search_knowledge",
  "read_source",
  "show_document",
  "focus_anchor",
  "show_evidence",
  "show_knowledge",
  "show_comparison",
  "show_relations",
  "show_artifact",
  "open_ingest_picker",
  "ingest_source",
  "get_job_status",
  "compare_sources",
  "get_relations",
  "render_chart",
  "create_document",
  "revise_document",
  "export_document",
  "start_research",
] as const

export type WorkspaceChatToolId = (typeof WORKSPACE_CHAT_TOOLS)[number]
