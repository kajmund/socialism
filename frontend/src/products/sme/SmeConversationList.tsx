import {
  MailOpen,
  MessageCircle,
  Search,
  UserRound,
  UsersRound,
} from "lucide-react"
import type {
  SmeInboxFilter,
  SmeInboxItem,
} from "@/api/sme"
import { useLocale } from "@/i18n"

type Props = {
  filter: SmeInboxFilter
  items: SmeInboxItem[]
  selected: SmeInboxItem | null
  search: string
  loading: boolean
  error: string | null
  onFilterChange: (filter: SmeInboxFilter) => void
  onSearchChange: (value: string) => void
  onSelect: (item: SmeInboxItem) => void
}

const filters: SmeInboxFilter[] = ["all", "unread", "groups"]

export function SmeConversationList({
  filter,
  items,
  selected,
  search,
  loading,
  error,
  onFilterChange,
  onSearchChange,
  onSelect,
}: Props) {
  const { t, intl } = useLocale()
  const filtered = items.filter((item) =>
    `${item.name} ${item.subtitle}`.toLocaleLowerCase().includes(
      search.trim().toLocaleLowerCase(),
    ),
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
            <button
              key={`${item.thread_type}:${item.thread_id}`}
              type="button"
              className={`relative flex w-full items-center gap-3 rounded-[var(--radius-md)] border py-2.5 pl-3 pr-8 text-left transition-colors ${
                active
                  ? "border-db-gold-500 bg-db-gold-100"
                  : "border-transparent hover:bg-db-ink-100"
              }`}
              onClick={() => onSelect(item)}
            >
              <span className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)] bg-db-ink-950 text-db-gold-500">
                {item.thread_type === "panel" ? (
                  <UsersRound size={19} aria-hidden="true" />
                ) : (
                  <UserRound size={19} aria-hidden="true" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-medium text-[color:var(--text-body)]">
                    {item.name}
                  </span>
                  <span className="shrink-0 text-[10px] text-[color:var(--text-muted)]">
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
              </span>
              {item.unread_count > 0 ? (
                <span
                  className="absolute right-3 top-1/2 size-2.5 -translate-y-1/2 rounded-full bg-db-gold-500"
                  aria-label={t("sme.unreadCount", { count: item.unread_count })}
                />
              ) : null}
            </button>
          )
        })}
      </div>
    </aside>
  )
}
