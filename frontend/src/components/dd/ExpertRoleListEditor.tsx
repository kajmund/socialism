import { blankExpertCatalogItem, type CatalogItem, type CatalogList } from "@/api/catalog"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"

export type ExpertRoleListEditorProps = {
  list: CatalogList
  draft: CatalogItem[]
  onChange: (items: CatalogItem[]) => void
  onSave: () => void
  saving: boolean
  dirty: boolean
  /** When false, hide the catalog key subtitle used on the config page. */
  showKeyMeta?: boolean
}

export function ExpertRoleListEditor({
  list,
  draft,
  onChange,
  onSave,
  saving,
  dirty,
  showKeyMeta = true,
}: ExpertRoleListEditorProps) {
  const { t } = useLocale()

  function patchItem(index: number, patch: Partial<CatalogItem>) {
    onChange(draft.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  }

  function removeItem(index: number) {
    onChange(draft.filter((_, i) => i !== index))
  }

  function addItem() {
    onChange([...draft, blankExpertCatalogItem()])
  }

  function moveItem(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= draft.length) return
    const next = [...draft]
    const [row] = next.splice(index, 1)
    next.splice(target, 0, row)
    onChange(next)
  }

  return (
    <Card className="gap-0 py-4 ring-1 ring-border">
      <CardContent className="px-5">
        <div className="sticky top-[88px] z-10 mb-3 flex items-start justify-between gap-3 border-b border-[color:var(--border-hairline)] bg-db-ink-0 py-3 md:top-[100px]">
          <div>
            <div className="text-sm font-medium text-[color:var(--text-body)]">{list.title}</div>
            {showKeyMeta ? (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {t("config.page.keyLabel", { key: list.key, count: draft.length })}
              </div>
            ) : (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {t("dd.experts.countLabel", { count: draft.length })}
              </div>
            )}
          </div>
          <AdminButton variant="accent" size="sm" disabled={!dirty || saving} onClick={onSave}>
            {saving ? t("common.saving") : t("common.save")}
          </AdminButton>
        </div>

        <ul className="flex flex-col gap-4">
          {draft.map((item, index) => (
            <li
              key={`${list.key}-${index}`}
              className="rounded-md border border-[color:var(--border-hairline)] p-4"
            >
              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium">{t("dd.expertpanel.labelField")}</span>
                  <input
                    className="dsearch"
                    value={item.label}
                    onChange={(e) => patchItem(index, { label: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium">{t("dd.expertpanel.descriptionField")}</span>
                  <textarea
                    rows={2}
                    className="dsearch"
                    value={item.description}
                    onChange={(e) => patchItem(index, { description: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium">{t("dd.expertpanel.kompetensField")}</span>
                  <input
                    className="dsearch"
                    value={item.kompetensomrade ?? ""}
                    onChange={(e) => patchItem(index, { kompetensomrade: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium">{t("dd.expertpanel.stilField")}</span>
                  <input
                    className="dsearch"
                    value={item.radgivningsstil ?? ""}
                    onChange={(e) => patchItem(index, { radgivningsstil: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium">{t("dd.expertpanel.bakgrundField")}</span>
                  <input
                    className="dsearch"
                    value={item.yrkesbakgrund ?? ""}
                    onChange={(e) => patchItem(index, { yrkesbakgrund: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium">{t("dd.expertpanel.anekdotField")}</span>
                  <textarea
                    rows={2}
                    className="dsearch"
                    value={item.professionell_anekdot ?? ""}
                    onChange={(e) => patchItem(index, { professionell_anekdot: e.target.value })}
                  />
                </label>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                  disabled={index === 0}
                  onClick={() => moveItem(index, -1)}
                  aria-label={t("config.page.moveUp")}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-muted-foreground hover:text-[color:var(--text-body)] disabled:opacity-30"
                  disabled={index === draft.length - 1}
                  onClick={() => moveItem(index, 1)}
                  aria-label={t("config.page.moveDown")}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="rounded border border-[color:var(--border-hairline)] px-2 py-1 text-xs text-destructive hover:bg-destructive/5"
                  onClick={() => removeItem(index)}
                >
                  {t("dd.expertpanel.removeRole")}
                </button>
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <AdminButton variant="secondary" size="sm" onClick={addItem}>
            {t("dd.expertpanel.addRole")}
          </AdminButton>
          <AdminButton variant="accent" size="sm" disabled={!dirty || saving} onClick={onSave}>
            {saving ? t("common.saving") : t("common.save")}
          </AdminButton>
        </div>
      </CardContent>
    </Card>
  )
}
