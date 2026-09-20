import { Phone, PhoneOff } from "lucide-react"
import { ExpertVoiceCallOverlay } from "@/components/chat/ExpertVoiceCallOverlay"
import type { GeminiLiveVoiceError } from "@/components/chat/geminiLiveVoice"
import { useGeminiLiveVoice } from "@/components/chat/useGeminiLiveVoice"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function voiceErrorText(error: GeminiLiveVoiceError, t: Translate): string {
  switch (error) {
    case "microphoneDenied":
      return t("chat.voice.errors.microphoneDenied")
    case "microphoneUnavailable":
      return t("chat.voice.errors.microphoneUnavailable")
    case "connectionFailed":
      return t("chat.voice.errors.connectionFailed")
    case "sessionFailed":
      return t("chat.voice.errors.sessionFailed")
    default: {
      const exhaustive: never = error
      return exhaustive
    }
  }
}

export function ExpertVoiceButton({
  personaId,
  expertName,
  avatarUrl,
  onErrorMessage,
}: {
  personaId: string | null
  expertName: string
  avatarUrl?: string | null
  onErrorMessage?: (message: string) => void
}) {
  const { t } = useLocale()
  const {
    state,
    toggle,
    microphoneMuted,
    speakerMuted,
    toggleMicrophone,
    toggleSpeaker,
  } = useGeminiLiveVoice({
    personaId,
    onError: (error) => onErrorMessage?.(voiceErrorText(error, t)),
    onMemoryError: () => onErrorMessage?.(t("chat.voice.memorySaveFailed")),
    onToolError: (name) =>
      onErrorMessage?.(t("chat.voice.toolFailed", { name })),
  })
  const running =
    state === "connecting" || state === "ringing" || state === "active"
  const status =
    state === "connecting"
      ? t("chat.voice.connecting")
      : state === "ringing"
        ? t("chat.voice.call.ringing")
      : state === "active"
        ? t("chat.voice.active")
        : t("chat.voice.startAria")

  return (
    <>
      <AdminButton
        variant="secondary"
        size="sm"
        className={
          "size-8 shrink-0 p-0 " +
          (state === "active"
            ? "border-db-gold-500 bg-db-gold-100 text-db-gold-700"
            : state === "connecting"
              ? "animate-pulse border-db-gold-500 text-db-gold-700"
              : state === "error"
                ? "border-destructive text-destructive"
                : "")
        }
        disabled={!personaId}
        aria-label={
          running ? t("chat.voice.stopAria") : t("chat.voice.startAria")
        }
        aria-pressed={running}
        title={status}
        onClick={toggle}
      >
        {running ? (
          <PhoneOff className="size-4" aria-hidden="true" />
        ) : (
          <Phone className="size-4" aria-hidden="true" />
        )}
      </AdminButton>
      <span className="sr-only" aria-live="polite">
        {status}
      </span>
      {running ? (
        <ExpertVoiceCallOverlay
          state={state}
          expertName={expertName}
          avatarUrl={avatarUrl}
          microphoneMuted={microphoneMuted}
          speakerMuted={speakerMuted}
          onToggleMicrophone={toggleMicrophone}
          onToggleSpeaker={toggleSpeaker}
          onHangUp={toggle}
        />
      ) : null}
    </>
  )
}
