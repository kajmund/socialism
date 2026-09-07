import { env } from "@/lib/env"

export function connectExpertgranskningWatch(options: {
  token: string
  jobId: string
  onMessage: (data: unknown) => void
  onClose?: () => void
}): { close: () => void } {
  const base = env.wsBaseUrl.replace(/\/$/, "")
  const url = `${base}/ws/expertgranskning?access_token=${encodeURIComponent(options.token)}`
  const socket = new WebSocket(url)
  let closedByUser = false

  socket.onopen = () => {
    socket.send(
      JSON.stringify({
        type: "hello",
        scope: "expertgranskning_watch",
        job_id: options.jobId,
      }),
    )
  }
  socket.onmessage = (event) => {
    try {
      options.onMessage(JSON.parse(String(event.data)))
    } catch {
      // Ignore non-JSON frames.
    }
  }
  socket.onclose = () => {
    if (!closedByUser) options.onClose?.()
  }

  return {
    close() {
      closedByUser = true
      socket.close()
    },
  }
}
