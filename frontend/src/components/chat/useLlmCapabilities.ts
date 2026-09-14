import { useCallback, useEffect, useState } from "react"
import {
  getLlmCapabilities,
  type LlmCapabilities,
} from "@/api/llmCapabilities"

const DEFAULT_ACCEPT = "image/jpeg,image/png,image/gif,image/webp"

/**
 * Active chat-LLM vision capability for persona / run interview attach UI.
 * Refetches on mount and when the window regains focus.
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
    window.addEventListener("focus", onFocus)
    return () => window.removeEventListener("focus", onFocus)
  }, [refresh])

  const allowImageAttach = Boolean(capabilities?.supports_vision)
  const imageAccept =
    capabilities?.allowed_image_types?.length
      ? capabilities.allowed_image_types.join(",")
      : DEFAULT_ACCEPT

  return { capabilities, allowImageAttach, imageAccept, refresh }
}
