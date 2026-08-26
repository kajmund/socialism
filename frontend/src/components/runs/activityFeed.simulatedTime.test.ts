import { describe, expect, it } from "vitest"
import type { OasisVariantResult } from "@/data/runs-types"
import {
  buildSimulatedTimeLabels,
  buildVariantSimulatedTimeLabels,
  buildTimelineItems,
  formatFeedWhenDisplay,
  isSimulatedClockTimestamp,
  simulatedTimeKeyForTraceRow,
  type TimelineActionItem,
} from "@/components/runs/activityFeed"

const t = (key: string) => key

function minutesFromHHMM(value: string): number {
  const [h, m] = value.split(":").map(Number)
  return h * 60 + m
}

describe("buildSimulatedTimeLabels", () => {
  it("maps monotonic created_at to non-decreasing HH:MM in the awake window", () => {
    const labels = buildSimulatedTimeLabels([
      { key: "a", createdAt: 100 },
      { key: "b", createdAt: 200 },
      { key: "c", createdAt: 300 },
    ])
    expect(labels.get("a")).toBe("08:00")
    expect(labels.get("c")).toBe("23:30")
    const minutes = ["a", "b", "c"].map((k) => minutesFromHHMM(labels.get(k)!))
    expect(minutes[0]).toBeLessThanOrEqual(minutes[1]!)
    expect(minutes[1]).toBeLessThanOrEqual(minutes[2]!)
  })

  it("is deterministic for the same input", () => {
    const events = [
      { key: "x", createdAt: 50 },
      { key: "y", createdAt: 150 },
    ]
    expect([...buildSimulatedTimeLabels(events)]).toEqual([
      ...buildSimulatedTimeLabels(events),
    ])
  })
})

describe("buildVariantSimulatedTimeLabels", () => {
  const variant: Pick<
    OasisVariantResult,
    "posts" | "comments" | "trace" | "tick_markers"
  > = {
    posts: [{ post_id: 1, user_id: 0, content: "Hej", created_at: 10, num_likes: 0, num_dislikes: 0, num_comments: 0 }],
    comments: [
      {
        comment_id: 1,
        post_id: 1,
        user_id: 2,
        content: "Kommentar",
        created_at: 30,
        num_likes: 0,
        num_dislikes: 0,
      },
    ],
    trace: [
      { user_id: 1, action: "like_post", created_at: 20, info: '{"post_id":1}' },
      { user_id: 1, action: "follow", created_at: 25, info: '{"follow_id":1}' },
      { user_id: 2, action: "do_nothing", created_at: 115, info: "{}" },
    ],
    tick_markers: [
      {
        tick_index: 0,
        day: 1,
        silent: false,
        key: "d1",
        rounds: 2,
        time_start: 1,
        time_end: 99,
      },
      {
        tick_index: 1,
        day: 2,
        silent: true,
        key: "d2",
        rounds: 1,
        time_start: 100,
        time_end: 199,
      },
    ],
  }

  it("keys trace rows by global trace index (matches timeline lookup)", () => {
    const labels = buildVariantSimulatedTimeLabels(variant)
    variant.trace!.forEach((row, traceIndex) => {
      const key = simulatedTimeKeyForTraceRow(row, traceIndex)
      expect(labels.has(key)).toBe(true)
    })
  })

  it("matches buildTimelineItems traceIndex for visible trace actions", () => {
    const labels = buildVariantSimulatedTimeLabels(variant)
    const timeline = buildTimelineItems(variant as OasisVariantResult, {
      hideNoise: true,
      agentName: () => "Agent",
      t,
    })
    const traceActions = timeline.filter(
      (item): item is TimelineActionItem =>
        item.kind === "action" && item.traceIndex != null,
    )
    expect(traceActions.length).toBeGreaterThan(0)
    for (const item of traceActions) {
      const key = simulatedTimeKeyForTraceRow(
        {
          user_id: item.userId,
          action: item.action,
          created_at: item.createdAt,
        },
        item.traceIndex!,
      )
      expect(labels.get(key)).toBeTruthy()
    }
  })
})

describe("formatFeedWhenDisplay", () => {
  it("returns simulated label for scenario-clock timestamps", () => {
    expect(formatFeedWhenDisplay(20, "sv-SE", "13:40")).toBe("13:40")
    expect(isSimulatedClockTimestamp(20)).toBe(true)
  })

  it("returns null for scenario-clock timestamps without a label", () => {
    expect(formatFeedWhenDisplay(20, "sv-SE", null)).toBeNull()
  })
})
