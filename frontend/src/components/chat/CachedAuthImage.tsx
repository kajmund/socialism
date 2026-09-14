import { useEffect, useState } from "react"
import { fetchCachedImageBlob } from "@/api/messages"

type CachedAuthImageProps = {
  sha256: string
  alt: string
  className?: string
}

/**
 * Loads a cached message image with Bearer auth (plain <img src> cannot).
 */
export function CachedAuthImage({ sha256, alt, className }: CachedAuthImageProps) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null
    setUrl(null)
    void fetchCachedImageBlob(sha256)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setUrl(null)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [sha256])

  if (!url) return null
  return <img src={url} alt={alt} className={className} />
}
