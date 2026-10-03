import type { WorkspaceCitation } from "@/api/workspaces"
import { safeSourceUrl } from "./workspaceChatState"

export function linkWorkspaceCitations(content: string, chatId: string, citations: WorkspaceCitation[]): string {
  const byLabel = new Map(citations.map((citation) => [citation.label, citation]))
  return content.replace(/\[(E\d+)\](?!\()/g, (text, label: string) => {
    const citation = byLabel.get(label)
    if (!citation) return text
    if (citation.source_object_id && citation.document_version_id && citation.text_unit_id) {
      const query = new URLSearchParams({ document_version_id: citation.document_version_id, text_unit_id: citation.text_unit_id })
      return `[${label}](/workspace-chats/${encodeURIComponent(chatId)}/sources/${encodeURIComponent(citation.source_object_id)}?${query})`
    }
    const url = safeSourceUrl(citation.source_url)
    return url ? `[${label}](${url.replace(/\(/g, "%28").replace(/\)/g, "%29")})` : text
  })
}
