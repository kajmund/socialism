import type { ExpertMemory } from "@/api/expertMemory"
import type { MessageKey, TranslateParams } from "@/i18n"

const NOTICE_TEXT_MAX = 96

export function clipNoticeText(text: string, max = NOTICE_TEXT_MAX): string {
  const trimmed = text.trim()
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, max).trimEnd()}…`
}

export function memoryNoticeText(
  memories: ExpertMemory[],
  t: (key: MessageKey, params?: TranslateParams) => string,
): string | null {
  if (memories.length === 0) return t("experts.memory.nothing")
  const first = clipNoticeText(memories[0]?.text ?? "")
  if (!first) return t("experts.memory.nothing")
  if (memories.length === 1) {
    return memories[0]?.event === "UPDATE"
      ? t("experts.memory.updated", { text: first })
      : t("experts.memory.saved", { text: first })
  }
  return t("experts.memory.savedMany", {
    text: first,
    count: String(memories.length - 1),
  })
}
