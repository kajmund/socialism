import { Card, CardContent } from "@/components/ui/card"
import type { OasisRunResults } from "@/data/runs-types"

type Props = {
  results: OasisRunResults
  status: string
}

export function OasisResultsPanel({ results, status }: Props) {
  const posts = results.posts ?? []
  const comments = results.comments ?? []
  const agents = results.agents ?? []

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
          <p className="mb-3 text-sm text-muted-foreground">
            Agenter:{" "}
            {agents.map((a) => a.member_name || a.username).join(", ")}
          </p>
        ) : null}

        {posts.length === 0 && !results.error ? (
          <p className="text-sm text-muted-foreground">Inga inlägg sparades.</p>
        ) : null}

        <ul className="flex flex-col gap-3">
          {posts.map((post) => {
            const author =
              agents.find((a) => a.index === post.user_id)?.member_name ??
              `agent ${post.user_id}`
            const postComments = comments.filter((c) => c.post_id === post.post_id)
            return (
              <li
                key={post.post_id}
                className="rounded-md border border-border bg-muted/30 px-3 py-2"
              >
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{author}</span>
                  <span>#{post.post_id}</span>
                  <span>{post.num_likes} likes</span>
                  {typeof post.num_shares === "number" ? (
                    <span>{post.num_shares} shares</span>
                  ) : null}
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {post.content}
                </p>
                {postComments.length > 0 ? (
                  <ul className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    {postComments.map((c) => (
                      <li key={c.comment_id} className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">
                          agent {c.user_id}:
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
