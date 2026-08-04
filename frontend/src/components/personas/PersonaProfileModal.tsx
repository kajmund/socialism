import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { getPersona, type PersonaDetail } from "@/api/personas"
import { PersonaAnekdotPresentation } from "@/components/personas/PersonaAnekdot"
import { AdminButton } from "@/components/ui/admin-button"
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
      setError(personaId ? null : "Ingen kopplad persona")
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
          err instanceof ApiError ? err.message : "Kunde inte hämta persona",
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, personaId])

  if (!open) return null

  const profile = persona?.profile
  const title = profile?.name ?? persona?.name ?? fallbackName ?? "Persona"

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
            Stäng
          </AdminButton>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Hämtar profil…</p>
          ) : null}

          {!loading && error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : null}

          {!loading && !error && profile ? (
            <div className="p-portrait-col" style={{ paddingRight: 0 }}>
              <div className="flex h-[160px] w-full items-center justify-center rounded bg-db-ink-100 text-sm text-[color:var(--text-muted)]">
                Porträtt av {profile.name}
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
                {profile.age} år, {profile.yrke}, {profile.ort} — {profile.parti}
              </div>
              <div className="p-sec">
                <div className="p-num">I.</div>
                <div className="p-lbl">Demografi</div>
                <p>
                  {profile.name} bor i <b>{profile.ort}</b> (
                  {profile.livssituation}) och arbetar som <b>{profile.yrke}</b>{" "}
                  med utbildningsnivå {profile.utbildning}.
                </p>
              </div>
              <div className="p-sec">
                <div className="p-num">II.</div>
                <div className="p-lbl">Värderingar</div>
                <p>
                  Politiskt lutar personen <b>{profile.lutning}</b>. Engagemang
                  kring {profile.sakfragor}. Förtroende: {profile.fortroende}.
                </p>
              </div>
              <div className="p-sec">
                <div className="p-num">III.</div>
                <div className="p-lbl">Röst & personlighet</div>
                <p>
                  Ton: <b>{profile.ton}</b>. Språkmönster: {profile.sprak}.
                  Medievanor: {profile.medievanor}.
                </p>
              </div>
              <div className="p-sec pol">
                <div className="p-num">IV.</div>
                <div className="p-lbl">Politik</div>
                <p>
                  Partisympati: <b>{profile.parti}</b>. Valdeltagande:{" "}
                  <b>{profile.valdeltagande}</b>.
                </p>
              </div>
              <PersonaAnekdotPresentation profile={profile} />
            </div>
          ) : null}

          {!loading && !error && !profile && fallbackName ? (
            <p className="text-sm text-muted-foreground">
              Ingen sparad profil för {fallbackName}.
            </p>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
