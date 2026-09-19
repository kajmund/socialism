import { useEffect, useState } from "react"
import { UserRound } from "lucide-react"
import { api } from "@/lib/api"

type Props = {
  avatarUrl?: string | null
  name: string
  className?: string
  iconSize?: number
}

export function ExpertAvatar({
  avatarUrl,
  name,
  className = "grid size-11 shrink-0 place-items-center overflow-hidden rounded-[var(--radius-md)] bg-db-ink-950 text-db-gold-500",
  iconSize = 19,
}: Props) {
  const [source, setSource] = useState<string | null>(null)

  useEffect(() => {
    setSource(null)
    if (!avatarUrl) return
    let cancelled = false
    let url: string | undefined
    void api.getBlob(avatarUrl).then((blob) => {
      if (!cancelled) {
        url = URL.createObjectURL(blob)
        setSource(url)
      }
    }).catch(() => {
      if (!cancelled) setSource(null)
    })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [avatarUrl])

  if (source) {
    return (
      <span className={className}>
        <img src={source} alt={name} className="size-full object-cover" />
      </span>
    )
  }

  return (
    <span className={className}>
      <UserRound size={iconSize} aria-hidden="true" />
    </span>
  )
}
