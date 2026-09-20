import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { Mic, MicOff, PhoneOff, Volume2, VolumeX } from "lucide-react"
import type { GeminiLiveVoiceState } from "@/components/chat/geminiLiveVoice"
import { ExpertAvatar } from "@/components/experts/ExpertAvatar"
import { useLocale } from "@/i18n"

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
}

export function ExpertVoiceCallOverlay({
  state,
  expertName,
  avatarUrl,
  microphoneMuted,
  speakerMuted,
  onToggleMicrophone,
  onToggleSpeaker,
  onHangUp,
}: {
  state: GeminiLiveVoiceState
  expertName: string
  avatarUrl?: string | null
  microphoneMuted: boolean
  speakerMuted: boolean
  onToggleMicrophone: () => void
  onToggleSpeaker: () => void
  onHangUp: () => void
}) {
  const { t } = useLocale()
  const [duration, setDuration] = useState(0)

  useEffect(() => {
    if (state !== "active") {
      setDuration(0)
      return
    }
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setDuration(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [state])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onHangUp()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [onHangUp])

  const status =
    state === "connecting"
      ? t("chat.voice.call.connecting")
      : state === "ringing"
        ? t("chat.voice.call.ringing")
        : t("chat.voice.call.connected")

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1300] grid place-items-center bg-db-ink-950/90 md:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={t("chat.voice.call.dialogAria", { name: expertName })}
    >
      <section className="relative flex size-full max-h-[760px] max-w-[430px] flex-col overflow-hidden bg-db-ink-950 text-db-ink-0 shadow-2xl md:rounded-[28px] md:border md:border-db-ink-700">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_28%,rgba(201,160,66,0.28),transparent_34%),radial-gradient(circle_at_15%_85%,rgba(59,91,115,0.55),transparent_45%),linear-gradient(160deg,#24272b_0%,#101214_68%)]" />
        <div className="relative flex flex-1 flex-col items-center px-8 pb-10 pt-16 text-center">
          <p className="text-sm font-medium text-db-ink-300">{status}</p>
          <h2 className="mt-2 max-w-full truncate font-[var(--font-display)] text-2xl font-medium">
            {expertName}
          </h2>

          <div className="relative mt-12">
            <span
              className={
                "absolute -inset-4 rounded-full border border-db-gold-500/50 " +
                (state === "ringing" ? "animate-ping" : "")
              }
              aria-hidden="true"
            />
            <ExpertAvatar
              avatarUrl={avatarUrl}
              name={expertName}
              className="grid size-48 place-items-center overflow-hidden rounded-full border-2 border-db-ink-0/70 bg-db-ink-800 text-db-gold-500 shadow-2xl"
              iconSize={64}
            />
          </div>

          <p className="mt-8 font-mono text-sm tabular-nums text-db-ink-200">
            {state === "active" ? formatDuration(duration) : "00:00"}
          </p>

          <div className="mt-auto grid w-full grid-cols-3 gap-5 pt-12">
            <button
              type="button"
              className="flex flex-col items-center gap-2 text-xs text-db-ink-200"
              aria-label={
                microphoneMuted
                  ? t("chat.voice.call.unmute")
                  : t("chat.voice.call.mute")
              }
              onClick={onToggleMicrophone}
            >
              <span className="grid size-14 place-items-center rounded-full border border-db-ink-500 bg-db-ink-800/80">
                {microphoneMuted ? <MicOff size={23} /> : <Mic size={23} />}
              </span>
              {microphoneMuted
                ? t("chat.voice.call.unmute")
                : t("chat.voice.call.mute")}
            </button>

            <button
              type="button"
              className="flex flex-col items-center gap-2 text-xs text-db-ink-0"
              aria-label={t("chat.voice.call.hangUp")}
              onClick={onHangUp}
            >
              <span className="grid size-16 place-items-center rounded-full bg-red-600 shadow-lg shadow-red-950/40 hover:bg-red-500">
                <PhoneOff size={27} />
              </span>
              {t("chat.voice.call.hangUp")}
            </button>

            <button
              type="button"
              className="flex flex-col items-center gap-2 text-xs text-db-ink-200"
              aria-label={
                speakerMuted
                  ? t("chat.voice.call.speakerOn")
                  : t("chat.voice.call.speakerOff")
              }
              onClick={onToggleSpeaker}
            >
              <span className="grid size-14 place-items-center rounded-full border border-db-ink-500 bg-db-ink-800/80">
                {speakerMuted ? <VolumeX size={23} /> : <Volume2 size={23} />}
              </span>
              {speakerMuted
                ? t("chat.voice.call.speakerOn")
                : t("chat.voice.call.speakerOff")}
            </button>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  )
}
