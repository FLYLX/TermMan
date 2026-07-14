import { describe, expect, test } from "bun:test"

import {
  advanceChatHistoryOffset,
  buildStableChatMessageRows,
} from "../../src/components/Items/chatHistory"

describe("chat history pagination", () => {
  test("keeps existing row keys stable when older messages are prepended", () => {
    const current = [
      {
        role: "user",
        type: "chat_user",
        timestamp: "2026-07-14T10:00:01Z",
        content: "current question",
      },
      {
        role: "assistant",
        type: "chat_assistant",
        timestamp: "2026-07-14T10:00:02Z",
        content: "current answer",
      },
    ]
    const keysBefore = buildStableChatMessageRows(current).map((row) => row.key)
    const keysAfter = buildStableChatMessageRows([
      {
        role: "assistant",
        type: "chat_assistant",
        timestamp: "2026-07-14T09:59:59Z",
        content: "older answer",
      },
      ...current,
    ])
      .slice(1)
      .map((row) => row.key)

    expect(keysAfter).toEqual(keysBefore)
  })

  test("advances the offset by raw page size, not visible message count", () => {
    const rawPage = Array.from({ length: 20 }, (_, index) => ({ index }))
    expect(advanceChatHistoryOffset(20, rawPage)).toBe(40)
    expect(advanceChatHistoryOffset(40, [])).toBe(40)
  })
})
