export interface ChatHistoryMessage {
  role: string
  content: string
  type?: string
  timestamp?: string
}

export function getChatMessageKey(message: ChatHistoryMessage): string {
  return [
    message.role,
    message.type ?? "",
    message.timestamp ?? "",
    message.content,
  ].join("\u0001")
}

export function buildStableChatMessageRows<T extends ChatHistoryMessage>(
  messages: T[],
): Array<{ key: string; message: T }> {
  const occurrences = new Map<string, number>()
  const rows = new Array<{ key: string; message: T }>(messages.length)

  // Count from the newest end so prepending older history keeps existing keys stable.
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    const baseKey = getChatMessageKey(message)
    const occurrence = occurrences.get(baseKey) ?? 0
    occurrences.set(baseKey, occurrence + 1)
    rows[index] = { key: `${baseKey}\u0002${occurrence}`, message }
  }

  return rows
}

export function advanceChatHistoryOffset(
  currentOffset: number,
  rawPageMessages: unknown[] | undefined,
): number {
  return currentOffset + (rawPageMessages?.length ?? 0)
}
