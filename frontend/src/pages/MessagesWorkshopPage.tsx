import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  createMessage,
  generateVariants,
  summarizeUrl,
  type MessageType,
  type MessageVariant,
  type MessageVariantKey,
} from "@/api/messages"
import { AdminShell } from "@/components/layout/AdminShell"
import { MessageVariantsModal } from "@/components/messages/MessageVariantsModal"
import { AdminButton } from "@/components/ui/admin-button"
import { ApiError } from "@/lib/api"

type Step = "type" | "compose"

function suggestTitle(body: string): string {
  return body.slice(0, 60).replace(/\s+/g, " ").trim()
}

export function MessagesWorkshopPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>("type")
  const [messageType, setMessageType] = useState<MessageType | null>(null)

  const [body, setBody] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [title, setTitle] = useState("")
  const [selectedKey, setSelectedKey] = useState<MessageVariantKey | null>(null)

  const [audience, setAudience] = useState("")
  const [purpose, setPurpose] = useState("")
  const [tone, setTone] = useState("")

  const [variantsOpen, setVariantsOpen] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [variants, setVariants] = useState<MessageVariant[]>([])
  const [modalError, setModalError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(t)
  }, [toast])

  function pickType(t: MessageType) {
    setMessageType(t)
    setStep("compose")
    setError(null)
    setBody("")
    setSelectedKey(null)
    setVariants([])
    setModalError(null)
  }

  async function onSummarizeLink() {
    if (!messageType || !sourceUrl.trim()) return
    setSummarizing(true)
    setError(null)
    try {
      const res = await summarizeUrl({
        url: sourceUrl.trim(),
        message_type: messageType,
      })
      setSourceUrl(res.source_url)
      setBody(res.summary)
      setSelectedKey(null)
      setToast("Länken sammanfattades")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Kunde inte hämta länken")
    } finally {
      setSummarizing(false)
    }
  }

  function openVariantsModal() {
    if (!body.trim() && !sourceUrl.trim()) {
      setError("Skriv text eller ange en länk innan du genererar varianter")
      return
    }
    setError(null)
    setModalError(null)
    setVariantsOpen(true)
  }

  async function onGenerate() {
    if (!messageType) return
    if (!body.trim() && !sourceUrl.trim()) {
      setModalError("Saknar underlag — skriv text i verkstaden eller ange en länk")
      return
    }
    setGenerating(true)
    setModalError(null)
    try {
      const res = await generateVariants({
        type: messageType,
        raw_text: body.trim(),
        source_url: sourceUrl.trim() || null,
        audience: audience.trim(),
        purpose: purpose.trim(),
        tone: tone.trim(),
      })
      setVariants(res.variants)
    } catch (err: unknown) {
      setModalError(
        err instanceof ApiError ? err.message : "Kunde inte generera varianter",
      )
    } finally {
      setGenerating(false)
    }
  }

  function selectVariant(v: MessageVariant) {
    setBody(v.body)
    setSelectedKey(v.key)
    if (!title.trim()) {
      setTitle(suggestTitle(v.body))
    }
    setVariantsOpen(false)
    setToast(`Valde: ${v.label}`)
  }

  async function onSave() {
    if (!messageType) return
    const text = body.trim()
    if (!text) {
      setError("Skriv budskapet innan du sparar")
      return
    }
    const saveTitle = title.trim() || suggestTitle(text)
    if (!saveTitle) {
      setError("Ange en titel")
      return
    }
    setSaving(true)
    setError(null)
    try {
      await createMessage({
        type: messageType,
        title: saveTitle,
        body: text,
        source_url: sourceUrl.trim() || null,
        metadata: {
          variant: selectedKey ?? undefined,
          audience: audience.trim() || undefined,
          purpose: purpose.trim() || undefined,
          tone: tone.trim() || undefined,
        },
      })
      navigate("/messages")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Kunde inte spara")
    } finally {
      setSaving(false)
    }
  }

  return (
    <AdminShell>
      <div className="wrap max-w-3xl">
        <div className="head-row">
          <div>
            <p className="mb-1 text-sm text-muted-foreground">
              <Link to="/messages" className="underline-offset-2 hover:underline">
                Budskap
              </Link>
              {" / "}
              Verkstad
            </p>
            <h1>Budskapsverkstad</h1>
            <p className="muted">
              Skriv budskapet, hämta från en länk eller generera formuleringar — spara sedan
              till biblioteket.
            </p>
          </div>
        </div>

        {step === "type" && (
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            <button
              type="button"
              className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 p-6 text-left transition-colors hover:border-db-ink-950"
              onClick={() => pickType("post")}
            >
              <div className="text-lg font-medium">Post</div>
              <p className="mt-2 text-sm text-muted-foreground">
                Partipost eller socialt inlägg som injiceras i simuleringen.
              </p>
            </button>
            <button
              type="button"
              className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 p-6 text-left transition-colors hover:border-db-ink-950"
              onClick={() => pickType("news")}
            >
              <div className="text-lg font-medium">Nyhet</div>
              <p className="mt-2 text-sm text-muted-foreground">
                Nyhetspost — skriv text eller hämta från en valfri källänk.
              </p>
            </button>
          </div>
        )}

        {step === "compose" && messageType && (
          <div className="mt-6 space-y-6">
            <div className="flex items-center justify-between gap-3">
              <span className="rounded-full border border-[color:var(--border-hairline)] px-3 py-1 text-sm">
                Typ: {messageType === "post" ? "Post" : "Nyhet"}
              </span>
              <AdminButton
                variant="secondary"
                size="sm"
                onClick={() => {
                  setStep("type")
                  setMessageType(null)
                  setVariantsOpen(false)
                }}
              >
                Byt typ
              </AdminButton>
            </div>

            <div className="field">
              <label htmlFor="message-body">
                {messageType === "news" ? "Nyhetstext" : "Budskap"}
              </label>
              <textarea
                id="message-body"
                rows={8}
                className="w-full"
                placeholder={
                  messageType === "news"
                    ? "Skriv nyheten här, eller hämta från en länk…"
                    : "Skriv budskapet här, eller hämta från en länk…"
                }
                value={body}
                onChange={(e) => {
                  setBody(e.target.value)
                  if (selectedKey) setSelectedKey(null)
                }}
              />
            </div>

            <div className="field">
              <label htmlFor="source-url">Länk (valfri)</label>
              <div className="flex flex-wrap items-stretch gap-2">
                <input
                  id="source-url"
                  className="min-w-0 flex-1"
                  placeholder="https://…"
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      void onSummarizeLink()
                    }
                  }}
                />
                <AdminButton
                  variant="secondary"
                  className="shrink-0"
                  onClick={onSummarizeLink}
                  disabled={!sourceUrl.trim() || summarizing}
                >
                  {summarizing ? "Hämtar…" : "Hämta & sammanfatta"}
                </AdminButton>
              </div>
            </div>

            <div className="field">
              <label htmlFor="title">Titel (för listor)</label>
              <input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Kort titel — fylls i automatiskt om tom"
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <AdminButton variant="accent" onClick={onSave} disabled={saving}>
                {saving ? "Sparar…" : "Spara till biblioteket"}
              </AdminButton>
              <AdminButton variant="secondary" onClick={openVariantsModal}>
                Generera varianter…
              </AdminButton>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        )}
      </div>

      <MessageVariantsModal
        open={variantsOpen}
        generating={generating}
        error={modalError}
        variants={variants}
        audience={audience}
        purpose={purpose}
        tone={tone}
        onAudienceChange={setAudience}
        onPurposeChange={setPurpose}
        onToneChange={setTone}
        onGenerate={onGenerate}
        onSelect={selectVariant}
        onClose={() => setVariantsOpen(false)}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
