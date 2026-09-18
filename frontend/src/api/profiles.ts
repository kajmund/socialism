import { api } from "@/lib/api"
export const profileFields = ["first_name", "last_name", "job_title"] as const
export const organizationFields = ["organization_name", "organization_number", "address_line1", "address_line2", "postal_code", "city", "country_code"] as const
export type ProfileField = typeof profileFields[number]
export type OrganizationField = typeof organizationFields[number]
export type Profile = Record<ProfileField, string | null> & { id: string; avatar_url: string | null; profile_revision: number }
export type Organization = Record<OrganizationField, string | null>
export type Proposal = { id: string; conversation: string; target: string; target_label: string; changes: Record<string, string | null>; previous: Record<string, string | null>; status: string }
export const getProfile = () => api.get<Profile>("/me")
export const updateProfile = (changes: Partial<Record<ProfileField, string | null>>) => api.patch<Profile>("/me", changes)
