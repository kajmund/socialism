/** Match backend ``expert_role_key`` (slug from a display name). */
export function expertRoleKey(label: string): string {
  const slug = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
  return slug || "expert"
}

/** First unused catalog key for ``name``, suffixing _2, _3, … when taken. */
export function uniqueExpertKey(name: string, taken: Iterable<string>): string {
  const used = new Set(taken)
  const base = expertRoleKey(name)
  if (!used.has(base)) return base
  let n = 2
  while (used.has(`${base}_${n}`)) n += 1
  return `${base}_${n}`
}
