import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  cachedImageUrl,
  createMessage,
  generateVariants,
  getMessage,
  listImageCache,
  patchMessageImageCaption,
  summarizeUrl,
  updateMessage,
  uploadMessageImage,
  type ImageCacheEntry,
  type MessageType,
  type MessageVariant,
  type MessageVariantKey,
} from "@/api/messages"
import { AdminShell } from "@/components/layout/AdminShell"
import { MessageVariantsModal } from "@/components/messages/MessageVariantsModal"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

type Step = "type" | "compose"
type ContentMode = "text" | "image" | "image_text"

function suggestTitle(body: string, caption: string): string {
  const source = body.trim() || caption.trim()
  return source.slice(0, 60).replace(/\s+/g, " ").trim()
}

function metaString(meta: Record<string, unknown>, key: string): string {
  const v = meta[key]
  return typeof v === "string" ? v : ""
}

function metaVariant(meta: Record<string, unknown>): MessageVariantKey | null {
  const v = meta.variant
  if (v === "analytical" || v === "narrative" || v === "concise") return v
  return null
}

function typeLabel(type: MessageType, t: Translate): string {
  switch (type) {
    case "post":
      return t("messages.list.typePost")
    case "news":
      return t("messages.list.typeNews")
    default: {
      const exhaustive: never = type
      return exhaustive
    }
  }
}

function contentModeFromMessage(body: string, imageSha: string | null): ContentMode {
  if (imageSha && !body.trim()) return "image"
  if (imageSha) return "image_text"
  return "text"
}

export function MessagesWorkshopPage() {
  const { t, locale } = useLocale()
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id?: string }>()
  const isEdit = Boolean(editId)
  const [step, setStep] = useState<Step>(isEdit ? "compose" : "type")
  const [messageType, setMessageType] = useState<MessageType | null>(null)
  const [contentMode, setContentMode] = useState<ContentMode>("text")

  const [body, setBody] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [title, setTitle] = useState("")
  const [selectedKey, setSelectedKey] = useState<MessageVariantKey | null>(null)

  const [imageSha256, setImageSha256] = useState<string | null>(null)
  const [imageCaption, setImageCaption] = useState("")
  const [captionBaseline, setCaptionBaseline] = useState("")
  const [cacheEntries, setCacheEntries] = useState<ImageCacheEntry[]>([])
  const [uploadingImage, setUploadingImage] = useState(false)

  const [audience, setAudience] = useState("")
  const [purpose, setPurpose] = useState("")
  const [tone, setTone] = useState("")

  const [variantsOpen, setVariantsOpen] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [variants, setVariants] = useState<MessageVariant[]>([])
  const [modalError, setModalError] = useState<string | null>(null)
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const loadCache = useCallback(async () => {
    try {
      const data = await listImageCache()
      setCacheEntries(data.entries)
    } catch {
      setCacheEntries([])
    }
  }, [])

  useEffect(() => {
    if (step !== "compose") return
    void loadCache()
  }, [step, loadCache])

  useEffect(() => {
    if (!editId) return
    let cancelled = false
    setLoading(true)
    getMessage(editId)
      .then((msg) => {
        if (cancelled) return
        setMessageType(msg.type)
        setStep("compose")
        setBody(msg.body)
        setTitle(msg.title)
        setSourceUrl(msg.source_url ?? "")
        setSelectedKey(metaVariant(msg.metadata))
        setAudience(metaString(msg.metadata, "audience"))
        setPurpose(metaString(msg.metadata, "purpose"))
        setTone(metaString(msg.metadata, "tone"))
        const sha = msg.image_sha256
        setImageSha256(sha)
        const cap = msg.image_caption ?? ""
        setImageCaption(cap)
        setCaptionBaseline(cap)
        setContentMode(contentModeFromMessage(msg.body, sha))
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("messages.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editId])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  function pickType(next: MessageType) {
    setMessageType(next)
    setStep("compose")
    setError(null)
    setBody("")
    setContentMode("text")
    setImageSha256(null)
    setImageCaption("")
    setCaptionBaseline("")
    setSelectedKey(null)
    setVariants([])
    setModalError(null)
  }

  function applyCacheEntry(entry: ImageCacheEntry) {
    setImageSha256(entry.sha256)
    setImageCaption(entry.caption)
    setCaptionBaseline(entry.caption)
    if (!title.trim()) {
      setTitle(suggestTitle(body, entry.caption))
    }
  }

  async function onImageUpload(file: File | null) {
    if (!file) return
    setUploadingImage(true)
    setError(null)
    try {
      const res = await uploadMessageImage(file, locale === "en" ? "en" : "sv")
      applyCacheEntry(res.entry)
      setToast(
        res.cache_hit
          ? t("messages.workshop.imageCacheHit")
          : t("messages.workshop.imageCaptionReady"),
      )
      await loadCache()
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("messages.workshop.imageUploadError"))
    } finally {
      setUploadingImage(false)
    }
  }

  async function syncCaptionIfDirty(): Promise<boolean> {
    if (!imageSha256) return true
    const next = imageCaption.trim()
    if (!next) {
      setError(t("messages.workshop.captionRequired"))
      return false
    }
    if (next === captionBaseline.trim()) return true
    try {
      const updated = await patchMessageImageCaption(imageSha256, next)
      setCaptionBaseline(updated.caption)
      await loadCache()
      return true
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("messages.workshop.captionSaveError"))
      return false
    }
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
      setContentMode("text")
      setImageSha256(null)
      setImageCaption("")
      setCaptionBaseline("")
      setToast(t("messages.workshop.summarizeSuccess"))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("messages.workshop.summarizeError"))
    } finally {
      setSummarizing(false)
    }
  }

  function openVariantsModal() {
    if (!body.trim() && !sourceUrl.trim()) {
      setError(t("messages.workshop.needBodyOrLink"))
      return
    }
    setError(null)
    setModalError(null)
    setVariantsOpen(true)
  }

  async function onGenerate() {
    if (!messageType) return
    if (!body.trim() && !sourceUrl.trim()) {
      setModalError(t("messages.workshop.missingInput"))
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
        err instanceof ApiError ? err.message : t("messages.workshop.variantsGenerateError"),
      )
    } finally {
      setGenerating(false)
    }
  }

  function selectVariant(v: MessageVariant) {
    setBody(v.body)
    setSelectedKey(v.key)
    if (!title.trim()) {
      setTitle(suggestTitle(v.body, imageCaption))
    }
    setVariantsOpen(false)
    setToast(t("messages.workshop.selectedToast", { label: v.label }))
  }

  function onContentModeChange(next: ContentMode) {
    setContentMode(next)
    setError(null)
    if (next === "text") {
      setImageSha256(null)
      setImageCaption("")
      setCaptionBaseline("")
    }
  }

  async function onSave() {
    if (!messageType) return
    const text = contentMode === "image" ? "" : body.trim()
    const needsImage = contentMode === "image" || contentMode === "image_text"
    if (needsImage && !imageSha256) {
      setError(t("messages.workshop.imageRequired"))
      return
    }
    if (contentMode === "text" && !text) {
      setError(t("messages.workshop.saveBodyRequired"))
      return
    }
    if (needsImage) {
      const ok = await syncCaptionIfDirty()
      if (!ok) return
    }
    const saveTitle =
      title.trim() || suggestTitle(text, imageCaption) || t("messages.workshop.imageOnlyTitleFallback")
    if (!saveTitle) {
      setError(t("messages.workshop.titleRequired"))
      return
    }
    setSaving(true)
    setError(null)
    const payload = {
      type: messageType,
      title: saveTitle,
      body: text,
      source_url: sourceUrl.trim() || null,
      metadata: {
        variant: selectedKey ?? undefined,
        audience: audience.trim() || undefined,
        purpose: purpose.trim() || undefined,
        tone: tone.trim() || undefined,
        image_sha256: needsImage ? imageSha256 ?? undefined : undefined,
      },
    }
    try {
      if (isEdit && editId) {
        await updateMessage(editId, payload)
        setToast(t("messages.workshop.savedToast"))
      } else {
        await createMessage(payload)
      }
      navigate("/messages")
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("common.saveError"))
    } finally {
      setSaving(false)
    }
  }

  const showBody = contentMode === "text" || contentMode === "image_text"
  const showImage = contentMode === "image" || contentMode === "image_text"

  return (
    <AdminShell>
      <div className="wrap max-w-3xl">
        <div className="head-row">
          <div>
            <p className="mb-1 text-sm text-muted-foreground">
              <Link to="/messages" className="underline-offset-2 hover:underline">
                {t("messages.list.title")}
              </Link>
              {" / "}
              {t("messages.workshop.breadcrumbWorkshop")}
            </p>
            <h1>{isEdit ? t("messages.workshop.editTitle") : t("messages.workshop.newTitle")}</h1>
            <p className="muted">
              {isEdit ? t("messages.workshop.editIntro") : t("messages.workshop.newIntro")}
            </p>
          </div>
        </div>

        {loading && <p className="muted">{t("messages.list.loading")}</p>}

        {!loading && step === "type" && (
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            <button
              type="button"
              className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 p-6 text-left transition-colors hover:border-db-ink-950"
              onClick={() => pickType("post")}
            >
              <div className="text-lg font-medium">{t("messages.list.typePost")}</div>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("messages.workshop.postTypeDesc")}
              </p>
            </button>
            <button
              type="button"
              className="rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 p-6 text-left transition-colors hover:border-db-ink-950"
              onClick={() => pickType("news")}
            >
              <div className="text-lg font-medium">{t("messages.list.typeNews")}</div>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("messages.workshop.newsTypeDesc")}
              </p>
            </button>
          </div>
        )}

        {!loading && step === "compose" && messageType && (
          <div className="mt-6 space-y-6">
            <div className="flex items-center justify-between gap-3">
              <span className="rounded-full border border-[color:var(--border-hairline)] px-3 py-1 text-sm">
                {t("messages.workshop.typeLabel", { type: typeLabel(messageType, t) })}
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
                {t("messages.workshop.changeType")}
              </AdminButton>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("messages.workshop.contentModeLabel")}</legend>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ["text", "messages.workshop.contentModeText"],
                    ["image", "messages.workshop.contentModeImage"],
                    ["image_text", "messages.workshop.contentModeImageText"],
                  ] as const
                ).map(([mode, labelKey]) => (
                  <label
                    key={mode}
                    className="flex cursor-pointer items-center gap-2 rounded border border-[color:var(--border-hairline)] px-3 py-2 text-sm"
                  >
                    <input
                      type="radio"
                      name="content-mode"
                      checked={contentMode === mode}
                      onChange={() => onContentModeChange(mode)}
                    />
                    {t(labelKey)}
                  </label>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">{t("messages.workshop.contentModeHint")}</p>
            </fieldset>

            {showImage ? (
              <div className="space-y-4 rounded border border-[color:var(--border-hairline)] p-4">
                <div className="field">
                  <label htmlFor="message-image-upload">{t("messages.workshop.imageUploadLabel")}</label>
                  <input
                    id="message-image-upload"
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    disabled={uploadingImage}
                    onChange={(e) => {
                      const file = e.target.files?.[0] ?? null
                      void onImageUpload(file)
                      e.target.value = ""
                    }}
                  />
                  {uploadingImage ? (
                    <p className="text-sm text-muted-foreground">{t("messages.workshop.imageUploading")}</p>
                  ) : null}
                </div>

                {cacheEntries.length > 0 ? (
                  <div className="field">
                    <p className="mb-2 text-sm font-medium">{t("messages.workshop.imagePickCached")}</p>
                    <div
                      role="listbox"
                      aria-label={t("messages.workshop.imagePickCached")}
                      className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
                    >
                      {cacheEntries.map((row) => {
                        const selected = imageSha256 === row.sha256
                        return (
                          <button
                            key={row.sha256}
                            type="button"
                            role="option"
                            aria-selected={selected}
                            aria-label={t("messages.workshop.imagePickOption", {
                              caption: row.caption.slice(0, 80),
                            })}
                            className={`overflow-hidden rounded border text-left transition-colors ${
                              selected
                                ? "border-db-ink-950 ring-2 ring-db-ink-950"
                                : "border-[color:var(--border-hairline)] hover:border-db-ink-950"
                            }`}
                            onClick={() => applyCacheEntry(row)}
                          >
                            <img
                              src={cachedImageUrl(row.sha256)}
                              alt=""
                              className="aspect-[4/3] w-full object-cover"
                              loading="lazy"
                            />
                            <span className="line-clamp-2 px-2 py-1.5 text-xs text-muted-foreground">
                              {row.caption}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {imageSha256 ? (
                  <>
                    <img
                      src={cachedImageUrl(imageSha256)}
                      alt={t("messages.workshop.imagePreviewAlt")}
                      className="max-h-64 rounded border border-[color:var(--border-hairline)] object-contain"
                    />
                    <p className="font-mono text-xs text-muted-foreground">{imageSha256}</p>
                    <div className="field">
                      <label htmlFor="image-caption">{t("messages.workshop.captionLabel")}</label>
                      <textarea
                        id="image-caption"
                        rows={6}
                        className="w-full"
                        value={imageCaption}
                        onChange={(e) => setImageCaption(e.target.value)}
                        placeholder={t("messages.workshop.captionPlaceholder")}
                      />
                      <p className="text-sm text-muted-foreground">{t("messages.workshop.captionHint")}</p>
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}

            {showBody ? (
              <div className="field">
                <label htmlFor="message-body">
                  {messageType === "news"
                    ? t("messages.workshop.bodyLabelNews")
                    : contentMode === "image_text"
                      ? t("messages.workshop.bodyLabelImageText")
                      : t("messages.workshop.bodyLabelPost")}
                </label>
                <textarea
                  id="message-body"
                  rows={8}
                  className="w-full"
                  placeholder={
                    messageType === "news"
                      ? t("messages.workshop.bodyPlaceholderNews")
                      : t("messages.workshop.bodyPlaceholderPost")
                  }
                  value={body}
                  onChange={(e) => {
                    setBody(e.target.value)
                    if (selectedKey) setSelectedKey(null)
                  }}
                />
              </div>
            ) : null}

            {contentMode === "text" ? (
              <div className="field">
                <label htmlFor="source-url">{t("messages.workshop.sourceUrlLabel")}</label>
                <div className="flex flex-wrap items-stretch gap-2">
                  <input
                    id="source-url"
                    className="min-w-0 flex-1"
                    placeholder={t("messages.workshop.sourceUrlPlaceholder")}
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
                    {summarizing
                      ? t("messages.workshop.fetching")
                      : t("messages.workshop.fetchAndSummarize")}
                  </AdminButton>
                </div>
              </div>
            ) : null}

            <div className="field">
              <label htmlFor="title">{t("messages.workshop.titleLabel")}</label>
              <input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t("messages.workshop.titlePlaceholder")}
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <AdminButton variant="accent" onClick={() => void onSave()} disabled={saving || uploadingImage}>
                {saving
                  ? t("common.saving")
                  : isEdit
                    ? t("messages.workshop.saveChanges")
                    : t("messages.workshop.saveToLibrary")}
              </AdminButton>
              {contentMode === "text" ? (
                <AdminButton variant="secondary" onClick={openVariantsModal}>
                  {t("messages.workshop.generateVariantsButton")}
                </AdminButton>
              ) : null}
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
