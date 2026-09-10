export function JsonFallback({ value }: { value: unknown }) {
  return (
    <pre className="overflow-auto rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3 text-xs leading-5 text-[color:var(--text-body)]">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
