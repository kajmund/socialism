import { api } from "@/lib/api"

export type EmbeddingCacheEntry = {
  id: string
  model: string
  text: string
  dims: number
  updated_at: string
}

export type EmbeddingCacheList = {
  embedding_model: string
  cache_dir: string
  count: number
  entries: EmbeddingCacheEntry[]
}

export type EmbeddingCacheClear = {
  cleared: number
}

export function listEmbeddingCache(): Promise<EmbeddingCacheList> {
  return api.get<EmbeddingCacheList>("/embeddings/cache")
}

export function clearEmbeddingCache(): Promise<EmbeddingCacheClear> {
  return api.delete<EmbeddingCacheClear>("/embeddings/cache")
}
