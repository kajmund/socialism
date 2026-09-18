import { api } from "@/lib/api"
import type { Organization } from "@/api/profiles"

export type KundProjekt = {
  id: number
  customer_id: number
  name: string
  slug: string
}

export type Kund = Organization & {
  id: number
  name: string
  slug: string
  product: string | null
  available_modules: string[]
  projekt: KundProjekt[]
}

export function listKunder(): Promise<Kund[]> {
  return api.get<Kund[]>("/kunder")
}

export function getKund(id: number): Promise<Kund> {
  return api.get<Kund>(`/kunder/${id}`)
}

export function createKund(body: {
  name: string
  slug: string
  available_modules?: string[]
}): Promise<Kund> {
  return api.post<Kund>("/kunder", body)
}

export function updateKundModules(id: number, available_modules: string[]): Promise<Kund> {
  return api.patch<Kund>(`/kunder/${id}`, { available_modules })
}

export function updateKundProduct(id: number, product: string | null): Promise<Kund> {
  return api.patch<Kund>(`/kunder/${id}`, { product })
}
