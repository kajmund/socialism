import { useCallback, useEffect, useState } from "react"
import {
  getLlmCapabilities,
  type LlmCapabilities,
} from "@/api/llmCapabilities"

const DEFAULT_ACCEPT = "image/jpeg,image/png,image/gif,image/webp"

/** Dispatched after Tools → LLM save so open chat panes refresh vision UI. */
export const LLM_CAPABILITIES_CHANGED_EVENT = "llm-capabilities-changed"

/**
 * Active chat-LLM vision capability for persona / run interview attach UI.
 * Refetches on mount, focus, tab visibility, and after LLM settings save.
 */
export function useLlmCapabilities() {
  const [capabilities, setCapabilities] = useState<LlmCapabilities | null>(null)

  const refresh = useCallback(() => {
    void getLlmCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities(null))
  }, [])

  useEffect(() => {
    refresh()
    const onFocus = () => refresh()
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh()
    }
    const onChanged = () => refresh()
    window.addEventListener("focus", onFocus)
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener(LLM_CAPABILITIES_CHANGED_EVENT, onChanged)
    return () => {
      window.removeEventListener("focus", onFocus)
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener(LLM_CAPABILITIES_CHANGED_EVENT, onChanged)
    }
  }, [refresh])

  const allowImageAttach = Boolean(capabilities?.supports_vision)
  const imageAccept =
    capabilities?.allowed_image_types?.length
      ? capabilities.allowed_image_types.join(",")
      : DEFAULT_ACCEPT

  return { capabilities, allowImageAttach, imageAccept, refresh }
}
