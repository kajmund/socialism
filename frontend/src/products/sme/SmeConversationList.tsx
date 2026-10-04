import { useState } from "react"
import {
  MailOpen,
  MessageCircle,
  Search,
  UsersRound,
} from "lucide-react"
import { ExpertAvatar } from "@/components/experts/ExpertAvatar"
import type {
  SmeInboxFilter,
  SmeInboxItem,
} from "@/api/sme"
import { useLocale } from "@/i18n"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

type Props = {
  compact?: boolean
  scopeLabel?: string
  filter: SmeInboxFilter
  items: SmeInboxItem[]
  selected: SmeInboxItem | null
  search: string
  loading: boolean
  error: string | null
  onFilterChange: (filter: SmeInboxFilter) => void
  onSearchChange: (value: string) => void
  onSelect: (item: SmeInboxItem) => void
  onOpenExpertEditor: (item: SmeInboxItem) => void
}

const filters: SmeInboxFilter[] = ["all", "unread", "groups"]

export function SmeConversationList({
  compact = false,
  scopeLabel,
  filter,
  items,
  selected,
  search,
  loading,
  error,
  onFilterChange,
  onSearchChange,
  onSelect,
  onOpenExpertEditor,
}: Props) {
  const { t, intl } = useLocale()
  const [inboxOpen, setInboxOpen] = useState(false)
  const filtered = items.filter((item) =>
    (filter === "all" || (filter === "unread" ? item.unread_count > 0 : item.thread_type === "panel")) &&
    `${item.name} ${item.kompetensomrade} ${item.subtitle} ${item.preview}`
      .toLocaleLowerCase(intl)
      .includes(search.trim().toLocaleLowerCase(intl)),
  )

  function filterLabel(value: SmeInboxFilter): string {
    switch (value) {
      case "all":
        return t("sme.filterAll")
      case "unread":
        return t("sme.filterUnread")
      case "groups":
        return t("sme.filterGroups")
      default: {
        const exhaustive: never = value
        return exhaustive
      }
    }
  }

  function timeLabel(value: string | null): string {
    if (!value) return ""
    return new Intl.DateTimeFormat(intl, {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value))
  }

  if (compact) return <>
    <aside className="flex h-full min-h-0 w-16 shrink-0 flex-col border-r bg-db-ink-0 sm:w-20" aria-label={t("sme.chats")}>
      <button type="button" className="mx-auto my-3 grid size-10 shrink-0 place-items-center rounded-lg border hover:bg-db-ink-100" aria-label={t("sme.openInbox")} title={scopeLabel ? t("sme.inboxScope", { name: scopeLabel }) : t("sme.openInbox")} aria-haspopup="dialog" aria-expanded={inboxOpen} onClick={() => setInboxOpen(true)}>
        <Search size={18} aria-hidden="true" />
      </button>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-2 pb-4">
        {loading ? <span role="status" className="text-center text-xs text-muted-foreground">{t("sme.loading")}</span> : null}
        {error ? <button type="button" className="text-xs text-destructive" aria-label={error} onClick={() => setInboxOpen(true)}>{t("sme.loadError")}</button> : null}
        {!loading && !error && !filtered.length ? <span className="text-center text-xs text-muted-foreground">{t("sme.empty")}</span> : null}
        {filtered.map((item) => {
          const active = selected?.thread_type === item.thread_type && selected.thread_id === item.thread_id
          const readStatus = item.unread_count > 0 ? t("sme.unreadCount", { count: item.unread_count }) : t("sme.readConversation")
          return <button key={`${item.thread_type}:${item.thread_id}`} type="button" title={[item.name, item.preview || item.subtitle, timeLabel(item.last_message_at), readStatus].filter(Boolean).join(" · ")} aria-label={`${item.name} · ${readStatus}`} aria-pressed={active} className={`relative flex shrink-0 flex-col items-center gap-1 rounded-lg p-1 text-[10px] ${active ? "bg-db-gold-100 ring-1 ring-db-gold-500" : "hover:bg-db-ink-100"}`} onClick={() => onSelect(item)}>
            {item.thread_type === "panel" ? <span className="grid size-10 place-items-center rounded-lg bg-db-ink-950 text-db-gold-500"><UsersRound size={20} aria-hidden="true" /></span> : <ExpertAvatar avatarUrl={item.avatar_url} name={item.name} className="grid size-10 place-items-center overflow-hidden rounded-lg bg-db-ink-950 text-db-gold-500" iconSize={20} />}
            <span className="w-full truncate">{item.name}</span>
            {item.unread_count > 0 ? <span className="absolute -right-1 -top-1 grid min-w-4 place-items-center rounded-full bg-db-gold-500 px-1 text-[10px] font-semibold text-db-ink-950" aria-label={readStatus}>{new Intl.NumberFormat(intl).format(item.unread_count)}</span> : null}
          </button>
        })}
      </div>
    </aside>
    <Dialog open={inboxOpen} onOpenChange={setInboxOpen}>
      <DialogContent showCloseButton={false} style={{ minHeight: 0 }} className="theme-admin flex h-[min(85dvh,720px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[420px]">
        <DialogHeader className="flex-row items-center border-b px-4 py-3">
          <div className="min-w-0 flex-1"><DialogTitle>{t("sme.chats")}</DialogTitle>{scopeLabel ? <DialogDescription className="mt-1 truncate">{t("sme.inboxScope", { name: scopeLabel })}</DialogDescription> : null}</div>
          <DialogClose render={<AdminButton variant="secondary" size="sm" aria-label={t("common.close")}>{t("common.close")}</AdminButton>}>{t("common.close")}</DialogClose>
        </DialogHeader>
        <SmeConversationList filter={filter} items={items} selected={selected} search={search} loading={loading} error={error} onFilterChange={onFilterChange} onSearchChange={onSearchChange} onSelect={(item) => { onSelect(item); setInboxOpen(false) }} onOpenExpertEditor={(item) => { setInboxOpen(false); onOpenExpertEditor(item) }} />
      </DialogContent>
    </Dialog>
  </>

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-r border-[color:var(--border-hairline)] bg-db-ink-0 md:w-[360px] lg:w-[400px]">
      <div className="shrink-0 border-b border-[color:var(--border-hairline)] px-5 pb-4 pt-5">
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-db-gold-700">
          {t("sme.productName")}
        </p>
        <h1 className="font-[var(--font-display)] text-2xl font-normal tracking-tight text-[color:var(--text-body)]">
          {t("sme.chats")}
        </h1>
        <label className="mt-4 flex h-9 items-center gap-2 rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 text-[color:var(--text-muted)] focus-within:border-db-ink-400">
          <Search size={17} aria-hidden="true" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm text-[color:var(--text-body)] outline-none placeholder:text-[color:var(--text-muted)]"
            value={search}
            placeholder={t("sme.searchPlaceholder")}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <div className="mt-3 flex gap-1">
          {filters.map((value) => (
            <button
              key={value}
              type="button"
              className={`inline-flex items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === value
                  ? "bg-db-ink-950 text-db-ink-0"
                  : "text-[color:var(--text-muted)] hover:bg-db-ink-100 hover:text-[color:var(--text-body)]"
              }`}
              onClick={() => onFilterChange(value)}
              aria-pressed={filter === value}
            >
              {value === "all" ? (
                <MessageCircle size={14} aria-hidden="true" />
              ) : value === "unread" ? (
                <MailOpen size={14} aria-hidden="true" />
              ) : (
                <UsersRound size={14} aria-hidden="true" />
              )}
              {filterLabel(value)}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading ? (
          <p className="px-3 py-6 text-sm text-[color:var(--text-muted)]">
            {t("sme.loading")}
          </p>
        ) : null}
        {error ? (
          <p className="px-3 py-6 text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        {!loading && !error && filtered.length === 0 ? (
          <p className="px-3 py-6 text-sm text-[color:var(--text-muted)]">
            {t("sme.empty")}
          </p>
        ) : null}
        {filtered.map((item) => {
          const active =
            selected?.thread_type === item.thread_type &&
            selected.thread_id === item.thread_id
          return (
            <div
              key={`${item.thread_type}:${item.thread_id}`}
              className={`relative flex w-full items-center gap-3 rounded-[var(--radius-md)] border py-2.5 pl-3 pr-8 transition-colors ${
                active
                  ? "border-db-gold-500 bg-db-gold-100"
                  : "border-transparent hover:bg-db-ink-100"
              }`}
            >
              {item.thread_type === "expert" ? (
                <button
                  type="button"
                  className="shrink-0 transition-opacity hover:opacity-90"
                  aria-label={t("sme.expertEditorAria", { name: item.name })}
                  onClick={() => onOpenExpertEditor(item)}
                >
                  <ExpertAvatar
                    avatarUrl={item.avatar_url}
                    name={item.name}
                  />
                </button>
              ) : (
                <span className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)] bg-db-ink-950 text-db-gold-500">
                  <UsersRound size={19} aria-hidden="true" />
                </span>
              )}
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => onSelect(item)}
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="truncate text-sm font-medium text-[color:var(--text-body)]">
                    {item.name}
                  </span>
                  {item.thread_type === "expert" && item.kompetensomrade ? (
                    <span className="truncate text-xs text-[color:var(--text-muted)]">
                      {item.kompetensomrade}
                    </span>
                  ) : null}
                  <span className="ml-auto shrink-0 text-[10px] text-[color:var(--text-muted)]">
                    {timeLabel(item.last_message_at)}
                  </span>
                </span>
                <span
                  className={`block truncate text-sm ${
                    item.unread_count > 0
                      ? "font-medium text-[color:var(--text-body)]"
                      : "text-[color:var(--text-muted)]"
                  }`}
                >
                  {item.preview || item.subtitle}
                </span>
              </button>
              {item.unread_count > 0 ? (
                <span
                  className="absolute right-3 top-1/2 size-2.5 -translate-y-1/2 rounded-full bg-db-gold-500"
                  aria-label={t("sme.unreadCount", { count: item.unread_count })}
                />
              ) : null}
            </div>
          )
        })}
      </div>
    </aside>
  )
}
