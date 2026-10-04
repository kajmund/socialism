import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { Markdown } from "@/components/ui/markdown"
import { linkWorkspaceCitations } from "./workspaceCitations"

vi.mock("@/i18n", () => ({ useLocale: () => ({ t: (key: string) => key }) }))
vi.mock("@/api/messages", () => ({ fetchCachedImageBlob: vi.fn() }))

it("renders frozen citations as clickable links inside the messenger answer", () => {
  const content = linkWorkspaceCitations("Sex månader [E1].", "chat-a", [{
    label: "E1", source_object_id: "avtal", document_version_id: "version-1",
    text_unit_id: "unit-1", excerpt: "Sex månader",
  }])
  const html = renderToStaticMarkup(<MessengerChat
    messages={[{ id: 1, role: "assistant", content }]}
    renderMessageContent={(message) => <Markdown content={message.content} />}
    draft="" onDraftChange={() => undefined} onSend={() => undefined} placeholder=""
  />)
  expect(html).toContain('<a href="/workspace-chats/chat-a/sources/avtal?document_version_id=version-1&amp;text_unit_id=unit-1">E1</a>')
  expect(html).not.toContain("[E1](")
})
