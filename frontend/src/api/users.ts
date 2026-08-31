import { api } from "@/lib/api"
import type { Role } from "@/lib/auth"

export type UserAccountRow = {
  id: string
  email: string
  role: Role
  kund_id: number | null
  kund_name: string | null
  invited_at: string
  last_seen_at: string | null
}

export type UserInviteBody = {
  email: string
  role: Role
  kund_id?: number | null
}

export function listUsers(): Promise<UserAccountRow[]> {
  return api.get<UserAccountRow[]>("/users")
}

export function inviteUser(body: UserInviteBody): Promise<UserAccountRow> {
  return api.post<UserAccountRow>("/users/invite", body)
}

export function updateUser(
  id: string,
  body: { role?: Role; kund_id?: number | null },
): Promise<UserAccountRow> {
  return api.patch<UserAccountRow>(`/users/${id}`, body)
}
