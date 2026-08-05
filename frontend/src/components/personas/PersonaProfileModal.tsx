import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { getPersona, type PersonaDetail } from "@/api/personas"
import { PersonaAnekdotPresentation } from "@/components/personas/PersonaAnekdot"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

type PersonaProfileModalProps = {
  open: boolean
  personaId: string | null
  fallbackName?: string
  onClose: () => void
}

export function PersonaProfileModal({
  open,
  personaId,
  fallbackName,
  onClose,
}: PersonaProfileModalProps) {
  const { t } = useLocale()
  const overlayMouseDownRef = useRef(false)
  const [persona, setPersona] = useState<PersonaDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open || !personaId) {
      setPersona(null)
      setLoading(false)
      setError(personaId ? null : t("personas.profile.noLinkedPersona"))
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setPersona(null)
    getPersona(personaId)
      .then((data) => {
        if (!cancelled) setPersona(data)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(
          err instanceof ApiError ? err.message : t("personas.profile.loadError"),
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, personaId, t])

  if (!open) return null

  const profile = persona?.profile
  const title = profile?.name ?? persona?.name ?? fallbackName ?? t("personas.profile.fallbackTitle")

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="persona-profile-modal-title"
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div className="flex max-h-[min(880px,92vh)] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] px-5 py-4">
          <h2
            id="persona-profile-modal-title"
            className="text-base font-medium"
          >
            {title}
          </h2>
          <AdminButton variant="secondary" size="sm" onClick={onClose}>
            {t("common.close")}
          </AdminButton>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">{t("personas.profile.loadingProfile")}</p>
          ) : null}

          {!loading && error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : null}

          {!loading && !error && profile ? (
            <div className="p-portrait-col" style={{ paddingRight: 0 }}>
              <div className="flex h-[160px] w-full items-center justify-center rounded bg-db-ink-100 text-sm text-[color:var(--text-muted)]">
                {t("personas.profile.portraitOf", { name: profile.name })}
              </div>
              <h1
                className="p-name"
                style={{
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                  fontSize: 26,
                }}
              >
                {profile.name}
              </h1>
              <div className="p-tag">
                {t("personas.profile.tagLine", {
                  age: profile.age,
                  occupation: profile.yrke,
                  district: profile.ort,
                  party: profile.parti,
                })}
              </div>
              <div className="p-sec">
                <div className="p-num">I.</div>
                <div className="p-lbl">{t("personas.profile.sectionDemography")}</div>
                <p>
                  {t("personas.profile.demographyParagraph", {
                    name: profile.name,
                    district: profile.ort,
                    lifeSituation: profile.livssituation,
                    occupation: profile.yrke,
                    education: profile.utbildning,
                  })}
                </p>
              </div>
              <div className="p-sec">
                <div className="p-num">II.</div>
                <div className="p-lbl">{t("personas.profile.sectionValues")}</div>
                <p>
                  {t("personas.profile.valuesParagraph", {
                    leaning: profile.lutning,
                    issues: profile.sakfragor,
                    trust: profile.fortroende,
                  })}
                </p>
              </div>
              <div className="p-sec">
                <div className="p-num">III.</div>
                <div className="p-lbl">{t("personas.profile.sectionVoice")}</div>
                <p>
                  {t("personas.profile.voiceParagraph", {
                    tone: profile.ton,
                    language: profile.sprak,
                    media: profile.medievanor,
                  })}
                </p>
              </div>
              <div className="p-sec pol">
                <div className="p-num">IV.</div>
                <div className="p-lbl">{t("personas.profile.sectionPolitics")}</div>
                <p>
                  {t("personas.profile.politicsParagraph", {
                    party: profile.parti,
                    turnout: profile.valdeltagande,
                  })}
                </p>
              </div>
              <PersonaAnekdotPresentation profile={profile} />
            </div>
          ) : null}

          {!loading && !error && !profile && fallbackName ? (
            <p className="text-sm text-muted-foreground">
              {t("personas.profile.noSavedProfile", { name: fallbackName })}
            </p>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
