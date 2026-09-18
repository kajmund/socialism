import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { useLocale } from "@/i18n"
export function ProfileAvatar({ path }: { path?: string | null }) {
  const { t } = useLocale()
  const [source, setSource] = useState<string | null>(null)
  useEffect(() => {
    setSource(null)
    if (!path) return
    let cancelled = false
    let url: string | undefined
    void api.getBlob(path).then((blob) => {
      if (!cancelled) { url = URL.createObjectURL(blob); setSource(url) }
    }).catch(() => { if (!cancelled) setSource(null) })
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [path])
  return source ? <img src={source} alt={t("profile.avatar")} className="size-10 rounded-full object-cover" /> : null
}
