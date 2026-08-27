import { useEffect, useState } from "react"
import {
  getCatalogList,
  updateCatalogList,
  type CatalogItem,
  type CatalogList,
} from "@/api/catalog"
import { ExpertRoleListEditor } from "@/components/dd/ExpertRoleListEditor"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function sameExpertItems(a: CatalogItem[], b: CatalogItem[]) {
  if (a.length !== b.length) return false
  return a.every((item, i) => {
    const other = b[i]
    return (
      item.label === other.label &&
      item.description === other.description &&
      (item.kompetensomrade ?? "") === (other.kompetensomrade ?? "") &&
      (item.radgivningsstil ?? "") === (other.radgivningsstil ?? "") &&
      (item.yrkesbakgrund ?? "") === (other.yrkesbakgrund ?? "") &&
      (item.professionell_anekdot ?? "") === (other.professionell_anekdot ?? "")
    )
  })
}

export function DdExpertsPage() {
  const { t } = useLocale()
  const [list, setList] = useState<CatalogList | null>(null)
  const [draft, setDraft] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void getCatalogList("expert_roller")
      .then((row) => {
        if (cancelled) return
        setList(row)
        setDraft(row.items.map((item) => ({ ...item })))
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("dd.experts.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 2500)
    return () => window.clearTimeout(id)
  }, [toast])

  const dirty = list != null && !sameExpertItems(draft, list.items)

  async function save() {
    if (!list) return
    setSaving(true)
    setError(null)
    try {
      const saved = await updateCatalogList("expert_roller", draft)
      setList(saved)
      setDraft(saved.items.map((item) => ({ ...item })))
      setToast(t("dd.experts.saved"))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.experts.saveError"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="wrap">
      <div className="head-row">
        <div>
          <h1>{t("dd.experts.title")}</h1>
          <p className="intro">{t("dd.experts.intro")}</p>
        </div>
      </div>

      {loading ? <div className="no-match">{t("dd.experts.loading")}</div> : null}
      {error ? (
        <p className="mb-4 text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && list ? (
        <ExpertRoleListEditor
          list={list}
          draft={draft}
          dirty={dirty}
          saving={saving}
          showKeyMeta={false}
          onChange={setDraft}
          onSave={() => void save()}
        />
      ) : null}

      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      ) : null}
    </div>
  )
}
