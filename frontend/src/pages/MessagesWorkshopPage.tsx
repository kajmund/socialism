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
import { AdminButton } from "@/components/ui/admin-button"
import { ApiError } from "@/lib/api"

type Step = "type" | "compose"

export function MessagesWorkshopPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>("type")
  const [messageType, setMessageType] = useState<MessageType | null>(null)

  const [rawText, setRawText] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [audience, setAudience] = useState("")
  const [purpose, setPurpose] = useState("")
  const [tone, setTone] = useState("")

  const [summarizing, setSummarizing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [variants, setVariants] = useState<MessageVariant[]>([])
  const [selectedKey, setSelectedKey] = useState<MessageVariantKey | null>(null)
  const [editedBody, setEditedBody] = useState("")
  const [title, setTitle] = useState("")
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
    setVariants([])
    setSelectedKey(null)
    setEditedBody("")
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
      setRawText(res.summary)
      setToast("Länken sammanfattades")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Kunde inte hämta länken")
    } finally {
      setSummarizing(false)
    }
  }

  async function onGenerate() {
    if (!messageType) return
    if (messageType === "news" && !sourceUrl.trim()) {
      setError("Käll-URL är obligatorisk för nyheter")
      return
    }
    if (!rawText.trim() && !sourceUrl.trim()) {
      setError("Klistra in råtext eller en länk först")
      return
    }
    setGenerating(true)
    setError(null)
    try {
      const res = await generateVariants({
        type: messageType,
        raw_text: rawText.trim(),
        source_url: sourceUrl.trim() || null,
        audience: audience.trim(),
        purpose: purpose.trim(),
        tone: tone.trim(),
      })
      setVariants(res.variants)
      const first = res.variants[0]
      if (first) {
        setSelectedKey(first.key)
        setEditedBody(first.body)
        if (!title.trim()) {
          setTitle(first.body.slice(0, 60).replace(/\s+/g, " ").trim())
        }
      }
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Kunde inte generera varianter")
    } finally {
      setGenerating(false)
    }
  }

  function selectVariant(v: MessageVariant) {
    setSelectedKey(v.key)
    setEditedBody(v.body)
  }

  async function onSave() {
    if (!messageType) return
    if (!title.trim()) {
      setError("Ange en titel")
      return
    }
    if (!editedBody.trim()) {
      setError("Välj eller skriv ett budskap innan du sparar")
      return
    }
    if (messageType === "news" && !sourceUrl.trim()) {
      setError("Käll-URL är obligatorisk för nyheter")
      return
    }
    setSaving(true)
    setError(null)
    try {
      await createMessage({
        type: messageType,
        title: title.trim(),
        body: editedBody.trim(),
        source_url: sourceUrl.trim() || null,
        metadata: {
          variant: selectedKey,
          audience: audience.trim() || undefined,
          purpose: purpose.trim() || undefined,
          tone: tone.trim() || undefined,
          source_input: rawText.trim().slice(0, 500) || undefined,
        },
      })
      setToast("Sparat i biblioteket")
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
              Skapa post eller nyhet i tre parallella varianter, välj en och spara till
              biblioteket.
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
                Nyhetspost baserad på en källa (URL obligatorisk).
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
                }}
              >
                Byt typ
              </AdminButton>
            </div>

            <div className="field">
              <label htmlFor="raw-text">Råtext / underlag</label>
              <textarea
                id="raw-text"
                rows={5}
                className="w-full"
                placeholder="Klistra in råtext, anteckningar eller utkast…"
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="source-url">
                Länk {messageType === "news" ? "(obligatorisk)" : "(valfri)"}
              </label>
              <div className="flex flex-wrap gap-2">
                <input
                  id="source-url"
                  className="min-w-0 flex-1"
                  placeholder="https://…"
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                />
                <AdminButton
                  variant="secondary"
                  onClick={onSummarizeLink}
                  disabled={!sourceUrl.trim() || summarizing}
                >
                  {summarizing ? "Hämtar…" : "Hämta & sammanfatta"}
                </AdminButton>
              </div>
            </div>

            <div className="form-grid">
              <div className="field">
                <label htmlFor="audience">Målgrupp (valfritt)</label>
                <input
                  id="audience"
                  value={audience}
                  onChange={(e) => setAudience(e.target.value)}
                  placeholder="t.ex. småbarnsföräldrar i Norrköping"
                />
              </div>
              <div className="field">
                <label htmlFor="purpose">Syfte (valfritt)</label>
                <input
                  id="purpose"
                  value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}
                  placeholder="t.ex. bygga auktoritet / testa reaktion"
                />
              </div>
              <div className="field">
                <label htmlFor="tone">Tonläge (valfritt)</label>
                <input
                  id="tone"
                  value={tone}
                  onChange={(e) => setTone(e.target.value)}
                  placeholder="t.ex. saklig, varm, skarp"
                />
              </div>
            </div>

            <AdminButton onClick={onGenerate} disabled={generating}>
              {generating ? "Genererar tre varianter…" : "Generera varianter"}
            </AdminButton>

            {variants.length > 0 && (
              <div className="space-y-3">
                <h2 className="text-base font-medium">Välj variant</h2>
                <div className="grid gap-3 md:grid-cols-3">
                  {variants.map((v) => (
                    <button
                      key={v.key}
                      type="button"
                      onClick={() => selectVariant(v)}
                      className={
                        "rounded-[var(--radius-md)] border p-3 text-left text-sm transition-colors " +
                        (selectedKey === v.key
                          ? "border-db-gold-500 bg-db-gold-500/10"
                          : "border-[color:var(--border-hairline)] hover:border-db-ink-950")
                      }
                    >
                      <div className="mb-2 font-medium">{v.label}</div>
                      <p className="whitespace-pre-wrap text-muted-foreground line-clamp-6">
                        {v.body}
                      </p>
                    </button>
                  ))}
                </div>

                <div className="field">
                  <label htmlFor="edited-body">Redigera valt budskap</label>
                  <textarea
                    id="edited-body"
                    rows={6}
                    className="w-full"
                    value={editedBody}
                    onChange={(e) => setEditedBody(e.target.value)}
                  />
                </div>

                <div className="field">
                  <label htmlFor="title">Titel (för listor)</label>
                  <input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Kort titel"
                  />
                </div>

                <AdminButton variant="accent" onClick={onSave} disabled={saving}>
                  {saving ? "Sparar…" : "Spara till biblioteket"}
                </AdminButton>
              </div>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        )}
      </div>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
