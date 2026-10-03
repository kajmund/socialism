export const CHAT_MESSAGE_LIMIT = 40

export function latestChatMessages<T>(messages: T[]): T[] {
  if (messages.length <= CHAT_MESSAGE_LIMIT) return messages
  return messages.slice(messages.length - CHAT_MESSAGE_LIMIT)
}
