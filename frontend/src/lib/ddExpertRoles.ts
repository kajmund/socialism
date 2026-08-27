/** Match backend `expert_role_key()` in app/services/dd/expert_roles.py */
export function expertRoleKey(label: string): string {
  const slug = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
  return slug || "expert"
}
