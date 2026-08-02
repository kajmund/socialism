import { Card, CardContent } from "@/components/ui/card"
import type { OasisRunResults } from "@/data/runs-types"

type Props = {
  results: OasisRunResults
  status: string
}

function agentLabel(
  agents: NonNullable<OasisRunResults["agents"]>,
  userId: number,
): string {
  return agents.find((a) => a.index === userId)?.member_name ?? `agent ${userId}`
}

export function OasisResultsPanel({ results, status }: Props) {
  const posts = results.posts ?? []
  const comments = results.comments ?? []
  const agents = results.agents ?? []
  const postsById = new Map(posts.map((p) => [p.post_id, p]))

  return (
    <Card className="mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
      <CardContent className="px-5 py-4">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-base font-semibold text-foreground">
            Simuleringsresultat
          </h2>
          <span className="text-xs text-muted-foreground">
            {results.engine ?? "oasis"} · {status}
            {typeof results.ticks_run === "number"
              ? ` · ${results.ticks_run} tickar`
              : ""}
          </span>
        </div>

        {results.error ? (
          <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {results.error}
          </p>
        ) : null}

        {agents.length > 0 ? (
          <div className="mb-3 space-y-1 text-sm text-muted-foreground">
            {agents.some((a) => a.role === "injector") ? (
              <p>
                Injektorer:{" "}
                {agents
                  .filter((a) => a.role === "injector")
                  .map((a) => a.member_name || a.username)
                  .join(", ")}
              </p>
            ) : null}
            <p>
              Population:{" "}
              {agents
                .filter((a) => a.role !== "injector")
                .map((a) => a.member_name || a.username)
                .join(", ") || "—"}
            </p>
          </div>
        ) : null}

        {posts.length === 0 && !results.error ? (
          <p className="text-sm text-muted-foreground">Inga inlägg sparades.</p>
        ) : null}

        <ul className="flex flex-col gap-3">
          {posts.map((post) => {
            const agent = agents.find((a) => a.index === post.user_id)
            const author = agent?.member_name ?? `agent ${post.user_id}`
            const isInjector = agent?.role === "injector"
            const originalId = post.original_post_id ?? null
            const original = originalId != null ? postsById.get(originalId) : undefined
            const originalAuthor =
              original != null ? agentLabel(agents, original.user_id) : null
            const quote = (post.quote_content ?? "").trim()
            const isQuote = originalId != null && quote.length > 0
            const isRepost = originalId != null && quote.length === 0
            const postComments = comments.filter((c) => c.post_id === post.post_id)

            let kindLabel: string | null = null
            if (isInjector) kindLabel = "injektion"
            else if (isQuote) kindLabel = "citat"
            else if (isRepost) kindLabel = "delning"

            return (
              <li
                key={post.post_id}
                className="rounded-md border border-border bg-muted/30 px-3 py-2"
              >
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{author}</span>
                  {kindLabel ? (
                    <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                      {kindLabel}
                    </span>
                  ) : null}
                  <span>#{post.post_id}</span>
                  <span>{post.num_likes} likes</span>
                  {typeof post.num_shares === "number" ? (
                    <span>{post.num_shares} shares</span>
                  ) : null}
                </div>

                {isQuote ? (
                  <div className="space-y-2">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {quote}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Citerar {originalAuthor ?? "okänd"} #{originalId}
                    </p>
                  </div>
                ) : null}

                {isRepost ? (
                  <p className="text-sm text-muted-foreground">
                    Delade inlägg från {originalAuthor ?? "okänd"} #{originalId}
                  </p>
                ) : null}

                {!isQuote && !isRepost ? (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {post.content}
                  </p>
                ) : null}

                {postComments.length > 0 ? (
                  <ul className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    {postComments.map((c) => (
                      <li key={c.comment_id} className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">
                          {agentLabel(agents, c.user_id)}:
                        </span>{" "}
                        {c.content}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
