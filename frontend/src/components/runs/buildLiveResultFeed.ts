import { HIDDEN_ACTIONS, sortKeyFromCreatedAt } from "@/components/runs/activityFeed"
import type { LiveFeedCatalog } from "@/components/runs/LiveFeedList"
import type { FeedComment, FeedPost } from "@/components/runs/feedChrome"
import type { RunWatchActivityItem, RunWatchRound } from "@/data/runWatch-types"

export type BuiltLiveResultFeed = {
  catalog: LiveFeedCatalog
  postTick: Map<number, number>
}

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function firstId(...values: unknown[]): number | null {
  for (const value of values) {
    const id = asInt(value)
    if (id != null) return id
  }
  return null
}

function addUnique(ids: number[], id: number): number[] {
  return ids.includes(id) ? ids : [...ids, id]
}

function removeId(ids: number[], id: number): number[] {
  return ids.filter((row) => row !== id)
}

function chronologicalItems(
  rounds: RunWatchRound[],
): Array<{ item: RunWatchActivityItem; tickIndex: number }> {
  const sorted = [...rounds].sort(
    (a, b) => a.tickIndex - b.tickIndex || a.roundIndex - b.roundIndex,
  )
  const out: Array<{ item: RunWatchActivityItem; tickIndex: number }> = []
  for (const round of sorted) {
    for (const item of round.items) {
      if (HIDDEN_ACTIONS.has(item.action.trim().toLowerCase())) continue
      out.push({ item, tickIndex: round.tickIndex })
    }
  }
  return out
}

function emptyPost(
  postId: number,
  userId: number,
  content: string,
  createdAt?: string | number,
): FeedPost {
  return {
    post_id: postId,
    user_id: userId,
    original_post_id: null,
    quote_content: null,
    num_likes: 0,
    num_dislikes: 0,
    num_shares: 0,
    created_at: createdAt ?? 0,
    content,
    liked_by: [],
    disliked_by: [],
    shared_by: [],
  }
}

function emptyComment(
  commentId: number,
  postId: number,
  userId: number,
  content: string,
  createdAt?: string | number,
): FeedComment {
  return {
    comment_id: commentId,
    post_id: postId,
    user_id: userId,
    content,
    created_at: createdAt,
    liked_by: [],
    disliked_by: [],
  }
}

function ensurePost(
  posts: Map<number, FeedPost>,
  postTick: Map<number, number>,
  postId: number,
  tickIndex: number,
  seed: {
    userId: number
    content?: string
    createdAt?: string | number
  },
): FeedPost {
  const existing = posts.get(postId)
  if (existing) return existing
  const created = emptyPost(
    postId,
    seed.userId,
    seed.content ?? "",
    seed.createdAt,
  )
  posts.set(postId, created)
  if (!postTick.has(postId)) postTick.set(postId, tickIndex)
  return created
}

function upsertShare(
  post: FeedPost,
  userId: number,
  kind: "repost" | "quote",
  sharePostId?: number,
): FeedPost {
  const sharedBy = [...(post.shared_by ?? [])]
  const already = sharedBy.some(
    (row) =>
      row.user_id === userId &&
      row.kind === kind &&
      (sharePostId == null || row.share_post_id === sharePostId),
  )
  if (!already) {
    sharedBy.push({
      user_id: userId,
      kind,
      ...(sharePostId != null ? { share_post_id: sharePostId } : {}),
    })
  }
  return { ...post, shared_by: sharedBy, num_shares: sharedBy.length }
}

function sortPostsNewestFirst(posts: FeedPost[]): FeedPost[] {
  return [...posts].sort((a, b) => {
    const byTime =
      sortKeyFromCreatedAt(b.created_at) - sortKeyFromCreatedAt(a.created_at)
    if (byTime !== 0) return byTime
    return b.post_id - a.post_id
  })
}

function sortCommentsOldestFirst(comments: FeedComment[]): FeedComment[] {
  return [...comments].sort((a, b) => {
    const byTime =
      sortKeyFromCreatedAt(a.created_at) - sortKeyFromCreatedAt(b.created_at)
    if (byTime !== 0) return byTime
    return a.comment_id - b.comment_id
  })
}

export function commentsByPostId(
  comments: FeedComment[] | undefined,
): Map<number, FeedComment[]> {
  const map = new Map<number, FeedComment[]>()
  for (const comment of comments ?? []) {
    const bucket = map.get(comment.post_id) ?? []
    bucket.push(comment)
    map.set(comment.post_id, bucket)
  }
  for (const [postId, bucket] of map) {
    map.set(postId, sortCommentsOldestFirst(bucket))
  }
  return map
}

export function buildLiveResultFeed(
  rounds: RunWatchRound[],
  seed?: LiveFeedCatalog,
): BuiltLiveResultFeed {
  const posts = new Map<number, FeedPost>()
  const comments = new Map<number, FeedComment>()
  const postTick = new Map<number, number>()

  for (const post of seed?.posts ?? []) {
    posts.set(post.post_id, {
      ...post,
      liked_by: [...(post.liked_by ?? [])],
      disliked_by: [...(post.disliked_by ?? [])],
      shared_by: [...(post.shared_by ?? [])],
    })
  }
  for (const comment of seed?.comments ?? []) {
    comments.set(comment.comment_id, {
      ...comment,
      liked_by: [...(comment.liked_by ?? [])],
      disliked_by: [...(comment.disliked_by ?? [])],
    })
  }

  for (const { item, tickIndex } of chronologicalItems(rounds)) {
    const action = item.action.trim().toLowerCase()
    const postId = firstId(item.post_id, item.info?.post_id)
    const commentId = firstId(item.comment_id, item.info?.comment_id)
    const postUserId = firstId(item.info?.post_user_id)
    const commentUserId = firstId(item.info?.comment_user_id)

    if (action === "create_post" && postId != null) {
      const existing = posts.get(postId)
      const content =
        item.content || item.post_preview || existing?.content || ""
      const originalPostId = firstId(
        item.info?.original_post_id,
        existing?.original_post_id,
      )
      const quote =
        typeof item.info?.quote_content === "string"
          ? item.info.quote_content
          : existing?.quote_content
      posts.set(postId, {
        ...(existing ?? emptyPost(postId, item.user_id, content, item.created_at)),
        user_id: existing?.user_id || item.user_id,
        content,
        created_at: existing?.created_at ?? item.created_at ?? 0,
        original_post_id: originalPostId ?? existing?.original_post_id ?? null,
        quote_content: quote ?? existing?.quote_content ?? null,
      })
      postTick.set(postId, tickIndex)
      continue
    }

    if (action === "create_comment" && commentId != null) {
      const existing = comments.get(commentId)
      const parentId = postId ?? existing?.post_id ?? 0
      const content =
        item.content || item.comment_preview || existing?.content || ""
      comments.set(commentId, {
        ...(existing ??
          emptyComment(
            commentId,
            parentId,
            item.user_id,
            content,
            item.created_at,
          )),
        post_id: parentId || existing?.post_id || 0,
        user_id: existing?.user_id || item.user_id,
        content,
        created_at: existing?.created_at ?? item.created_at,
      })
      continue
    }

    if (postId != null) {
      const preview = item.post_preview
      const post = ensurePost(posts, postTick, postId, tickIndex, {
        userId: postUserId ?? 0,
        content: preview,
        createdAt: item.created_at,
      })
      if (action === "like_post") {
        const likedBy = addUnique(post.liked_by ?? [], item.user_id)
        posts.set(postId, {
          ...post,
          liked_by: likedBy,
          num_likes: likedBy.length,
        })
      } else if (action === "unlike_post") {
        const likedBy = removeId(post.liked_by ?? [], item.user_id)
        posts.set(postId, {
          ...post,
          liked_by: likedBy,
          num_likes: likedBy.length,
        })
      } else if (action === "dislike_post") {
        const dislikedBy = addUnique(post.disliked_by ?? [], item.user_id)
        posts.set(postId, {
          ...post,
          disliked_by: dislikedBy,
          num_dislikes: dislikedBy.length,
        })
      } else if (action === "undo_dislike_post") {
        const dislikedBy = removeId(post.disliked_by ?? [], item.user_id)
        posts.set(postId, {
          ...post,
          disliked_by: dislikedBy,
          num_dislikes: dislikedBy.length,
        })
      } else if (action === "repost") {
        posts.set(postId, upsertShare(post, item.user_id, "repost"))
      } else if (action === "quote_post") {
        posts.set(postId, upsertShare(post, item.user_id, "quote"))
      }
    }

    if (commentId != null) {
      const existing = comments.get(commentId)
      const parentId = postId ?? existing?.post_id ?? 0
      const comment =
        existing ??
        emptyComment(
          commentId,
          parentId,
          commentUserId ?? 0,
          item.comment_preview ?? "",
          item.created_at,
        )
      if (!existing) comments.set(commentId, comment)
      if (action === "like_comment") {
        comments.set(commentId, {
          ...comment,
          liked_by: addUnique(comment.liked_by ?? [], item.user_id),
        })
      } else if (action === "unlike_comment") {
        comments.set(commentId, {
          ...comment,
          liked_by: removeId(comment.liked_by ?? [], item.user_id),
        })
      } else if (action === "dislike_comment") {
        comments.set(commentId, {
          ...comment,
          disliked_by: addUnique(comment.disliked_by ?? [], item.user_id),
        })
      } else if (action === "undo_dislike_comment") {
        comments.set(commentId, {
          ...comment,
          disliked_by: removeId(comment.disliked_by ?? [], item.user_id),
        })
      }
    }
  }

  return {
    catalog: {
      posts: sortPostsNewestFirst([...posts.values()]),
      comments: sortCommentsOldestFirst([...comments.values()]),
      follows: seed?.follows,
      mutes: seed?.mutes,
      reports: seed?.reports,
    },
    postTick,
  }
}
