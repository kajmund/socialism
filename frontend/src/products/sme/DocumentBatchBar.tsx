export function DocumentBatchBar({ value }: { value: number }) {
  return (
    <div className="grid gap-1">
      <div className="h-2 overflow-hidden rounded bg-db-ink-100" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
        <div className="h-full bg-db-gold-500" style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs text-muted-foreground">{value} %</span>
    </div>
  )
}
