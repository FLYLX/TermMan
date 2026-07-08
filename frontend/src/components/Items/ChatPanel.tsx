import { Link } from "@tanstack/react-router"
import { ChevronDown, ChevronUp, ExternalLink, Loader2, Send, Square, Trash2 } from "lucide-react"
import { useEffect, useEffectEvent, useRef, useState } from "react"

import type { ItemHandlerPublic } from "@/client"
import { ItemHandlerAssociationsService } from "@/client"
import { OpenAPI } from "@/client/core/OpenAPI"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type TimelineRole = "user" | "assistant" | "terminal"
type TerminalSource = "filtered_output" | "raw_feedback"

interface AgentStatusState {
  text: string
  source?: TerminalSource | null
  autoClearMs?: number
}

interface ChatMessage {
  role: TimelineRole
  content: string
  type?: string
  timestamp?: string
  tool_name?: string
  localEcho?: boolean
}

interface ChatPanelProps {
  itemId: string
}

const STATUS_ONLY_TYPES = new Set([
  "agent_status",
  "agent_thinking",
  "agent_action",
  "agent_tool_result",
  "session_summary",
])

const COMPLETION_TYPES = new Set([
  "agent_response",
  "chat_assistant",
  "agent_warning",
  "agent_error",
])

const LIVE_REPLY_STATUS_TIMEOUT_MS = 90_000
const ACTIVE_AGENT_STATUS_TIMEOUT_MS = 180_000
const CHAT_HISTORY_PAGE_SIZE = 20
const TERMINAL_STATUS_DONE_STATES = new Set([
  "idle",
  "done",
  "complete",
  "completed",
  "aborted",
  "error",
  "interrupted",
])

const ROBOT_HEADER_RE = /^\[Robot message;\s*([^\]]+)\]/
const ROBOT_CURRENT_MESSAGE_RE = /\[Current QQ message\]\r?\n([\s\S]*)$/
const ROBOT_PENDING_LINE_RE =
  /^(\d+)\.\s+sender=([^;]+);\s+trigger=([^:]+):\s*(.*)$/
const CQ_REPLY_RE = /\[CQ:reply,id=([^\]]+)\]/g
const CQ_AT_RE = /\[CQ:at,qq=([^,\]]+)(?:,[^\]]*)?\]/g

type ChatSessionPage = {
  messages: ChatMessage[]
  total?: number
  offset?: number
  limit?: number | null
  has_more?: boolean
}

async function getChatSession(
  itemId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<ChatSessionPage> {
  const token = localStorage.getItem("access_token") || ""
  const params = new URLSearchParams()
  if (typeof options.limit === "number") {
    params.set("limit", String(options.limit))
  }
  if (typeof options.offset === "number") {
    params.set("offset", String(options.offset))
  }
  const query = params.toString()
  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/memory/${itemId}/session${query ? `?${query}` : ""}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  )

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`HTTP ${response.status} ${errorText}`)
  }

  return response.json()
}

async function clearChatSession(itemId: string): Promise<void> {
  const token = localStorage.getItem("access_token") || ""
  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/memory/${itemId}/session`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  )

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`HTTP ${response.status} ${errorText}`)
  }
}

function normalizeMessage(message: {
  role?: unknown
  content?: unknown
  type?: unknown
  timestamp?: unknown
  tool_name?: unknown
}): ChatMessage | null {
  if (typeof message.content !== "string") {
    return null
  }

  const type = typeof message.type === "string" ? message.type : undefined
  const timestamp =
    typeof message.timestamp === "string" ? message.timestamp : undefined
  const toolName =
    typeof message.tool_name === "string" ? message.tool_name : undefined

  if (
    message.role === "user" ||
    message.role === "assistant" ||
    message.role === "terminal"
  ) {
    return {
      role: message.role,
      content: message.content,
      type,
      timestamp,
      tool_name: toolName,
    }
  }

  if (type === "terminal_output") {
    return {
      role: "terminal",
      content: message.content,
      type,
      timestamp,
      tool_name: toolName,
    }
  }

  if (type === "chat_user") {
    return {
      role: "user",
      content: message.content,
      type,
      timestamp,
      tool_name: toolName,
    }
  }

  return {
    role: "assistant",
    content: message.content,
    type,
    timestamp,
    tool_name: toolName,
  }
}

function shouldRenderMessage(message: ChatMessage): boolean {
  return !STATUS_ONLY_TYPES.has(message.type ?? "")
}

function normalizeRenderableMessages(
  messages: ChatSessionPage["messages"] | undefined,
): ChatMessage[] {
  return (messages ?? [])
    .map((message) => normalizeMessage(message))
    .filter(
      (message): message is ChatMessage =>
        message !== null && shouldRenderMessage(message),
    )
}

function getChatMessageKey(message: ChatMessage): string {
  return [
    message.role,
    message.type ?? "",
    message.timestamp ?? "",
    message.content,
  ].join("\u0001")
}

function getVisibleChatContent(message: ChatMessage): string {
  if (message.role !== "user" || !message.content.includes("[Robot message;")) {
    return message.content
  }

  const currentMatch = message.content.match(ROBOT_CURRENT_MESSAGE_RE)
  if (!currentMatch) {
    return message.content
  }

  const current = currentMatch[1].trim()
  if (!current.startsWith("[Pending QQ messages;")) {
    return current || message.content
  }

  const pendingLines = current
    .split(/\r?\n/)
    .map((line) => {
      const match = line.match(ROBOT_PENDING_LINE_RE)
      if (!match) {
        return null
      }
      return `${match[1]}. ${match[2]}: ${match[4]}`
    })
    .filter((line): line is string => Boolean(line))

  return pendingLines.length > 0 ? pendingLines.join("\n") : current
}

type RobotPendingMessage = {
  index: string
  sender: string
  trigger: string
  content: string
}

type RobotMessageDisplay = {
  body: string
  conversationType: string | null
  conversationId: string | null
  trigger: string | null
  senderName: string | null
  senderId: string | null
  mentions: string[]
  replyIds: string[]
  pendingMessages: RobotPendingMessage[]
}

function parseRobotMetadata(content: string): Record<string, string> | null {
  const match = content.match(ROBOT_HEADER_RE)
  if (!match) {
    return null
  }

  return match[1].split(";").reduce<Record<string, string>>((metadata, part) => {
    const [rawKey, ...valueParts] = part.split("=")
    const key = rawKey.trim()
    const value = valueParts.join("=").trim()
    if (key && value) {
      metadata[key] = value
    }
    return metadata
  }, {})
}

function parseConversation(value: string | undefined): {
  type: string | null
  id: string | null
} {
  if (!value) {
    return { type: null, id: null }
  }

  const [type, ...idParts] = value.split(":")
  return {
    type: type || null,
    id: idParts.join(":") || value,
  }
}

function parseSender(value: string | undefined): {
  name: string | null
  id: string | null
} {
  if (!value) {
    return { name: null, id: null }
  }

  const match = value.match(/^(.*?)\s*\(([^()]+)\)$/)
  if (!match) {
    return { name: value.trim() || null, id: null }
  }

  return {
    name: match[1].trim() || null,
    id: match[2].trim() || null,
  }
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)))
}

function decodeRobotText(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&#91;/g, "[")
    .replace(/&#93;/g, "]")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
}

function cleanRobotQqContent(value: string): string {
  return decodeRobotText(value)
    .replace(CQ_REPLY_RE, "")
    .replace(CQ_AT_RE, "@$1 ")
    .replace(/\[CQ:image[^\]]*\]/g, "[图片]")
    .replace(/\[CQ:record[^\]]*\]/g, "[语音]")
    .replace(/\[CQ:video[^\]]*\]/g, "[视频]")
    .replace(/\[CQ:face[^\]]*\]/g, "[表情]")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

function parseRobotPendingMessages(current: string): RobotPendingMessage[] {
  if (!current.startsWith("[Pending QQ messages;")) {
    return []
  }

  return current
    .split(/\r?\n/)
    .map((line) => {
      const match = line.match(ROBOT_PENDING_LINE_RE)
      if (!match) {
        return null
      }
      return {
        index: match[1],
        sender: match[2].trim(),
        trigger: match[3].trim(),
        content: cleanRobotQqContent(match[4]),
      }
    })
    .filter((line): line is RobotPendingMessage => Boolean(line))
}

function getRobotMessageDisplay(message: ChatMessage): RobotMessageDisplay | null {
  if (message.role !== "user" || !message.content.includes("[Robot message;")) {
    return null
  }

  const metadata = parseRobotMetadata(message.content)
  const currentMatch = message.content.match(ROBOT_CURRENT_MESSAGE_RE)
  if (!metadata || !currentMatch) {
    return null
  }

  const current = currentMatch[1].trim()
  const pendingMessages = parseRobotPendingMessages(current)
  const { type, id } = parseConversation(metadata.conversation)
  const sender = parseSender(metadata.sender)
  const body = pendingMessages.length > 0 ? "" : cleanRobotQqContent(current)
  const mentionsFromHeader = (metadata.mentions ?? "")
    .split(",")
    .map((mention) => mention.trim())
    .filter(Boolean)
  const mentionsFromBody = Array.from(current.matchAll(CQ_AT_RE)).map(
    (match) => match[1],
  )

  return {
    body: body || current,
    conversationType: type,
    conversationId: id,
    trigger: metadata.trigger ?? null,
    senderName: sender.name,
    senderId: sender.id,
    mentions: uniqueValues([...mentionsFromHeader, ...mentionsFromBody]),
    replyIds: uniqueValues(
      Array.from(current.matchAll(CQ_REPLY_RE)).map((match) => match[1]),
    ),
    pendingMessages,
  }
}

function getConversationTypeLabel(type: string | null): string {
  if (type === "group") {
    return "群号"
  }

  if (type === "private") {
    return "私聊"
  }

  if (type === "channel") {
    return "频道"
  }

  return "对话"
}

function getTriggerLabel(trigger: string | null): string | null {
  if (!trigger) {
    return null
  }

  const labels: Record<string, string> = {
    active_chat_window: "已唤醒",
    mention_bot: "@机器人",
    pending_queue: "排队消息",
    plain: "普通消息",
    private: "私聊",
    reply_to_bot: "回复机器人",
  }

  return labels[trigger] ?? trigger
}

function formatChatTimestamp(timestamp: string | undefined): string | null {
  if (!timestamp) {
    return null
  }

  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) {
    return timestamp
  }

  return date.toLocaleString()
}

function RobotMetaPill({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}) {
  if (!value) {
    return null
  }

  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[10px] leading-4 text-foreground">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate font-medium">{value}</span>
    </span>
  )
}

function RobotMessageCard({
  display,
  timestamp,
}: {
  display: RobotMessageDisplay
  timestamp?: string
}) {
  const triggerLabel = getTriggerLabel(display.trigger) ?? "消息"
  const conversationLabel = display.conversationId
    ? `${getConversationTypeLabel(display.conversationType)} ${display.conversationId}`
    : getConversationTypeLabel(display.conversationType)

  return (
    <div className="w-full overflow-hidden rounded-lg border border-border border-l-sky-500 bg-card text-card-foreground shadow-sm">
      <div className="border-b border-border bg-muted/50 px-2.5 py-2">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
            <div className="flex min-w-0 items-center gap-2 text-[11px] font-semibold">
              <span className="shrink-0 text-sky-600 dark:text-sky-400">
                QQ → Agent
              </span>
              <span className="shrink-0 rounded-md bg-sky-500/10 px-1.5 py-0.5 text-sky-700 dark:text-sky-300">
                {triggerLabel}
              </span>
              <span className="min-w-0 truncate text-muted-foreground">
                {conversationLabel}
                {display.senderName ? ` · ${display.senderName}` : ""}
              </span>
            </div>
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <RobotMetaPill label="时间" value={formatChatTimestamp(timestamp)} />
            <RobotMetaPill
              label={getConversationTypeLabel(display.conversationType)}
              value={display.conversationId}
            />
            <RobotMetaPill label="触发" value={triggerLabel} />
            <RobotMetaPill label="发送者" value={display.senderName} />
            <RobotMetaPill label="QQ" value={display.senderId} />
            <RobotMetaPill label="回复ID" value={display.replyIds.join(", ")} />
            <RobotMetaPill label="@" value={display.mentions.join(", ")} />
          </div>
        </details>
      </div>
      <div className="px-3 py-2 text-sm leading-6">
        {display.pendingMessages.length > 0 ? (
          <div className="divide-y divide-border">
            {display.pendingMessages.map((pending) => (
              <div
                key={`${pending.index}-${pending.sender}`}
                className="py-1.5 first:pt-0 last:pb-0"
              >
                <div className="mb-0.5 flex min-w-0 items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="shrink-0 font-mono">#{pending.index}</span>
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {pending.sender}
                  </span>
                  <span className="shrink-0">
                    {getTriggerLabel(pending.trigger) ?? pending.trigger}
                  </span>
                </div>
                <div className="whitespace-pre-wrap break-words">
                  {pending.content || "[空消息]"}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="whitespace-pre-wrap break-words">
            {display.body || "[空消息]"}
          </div>
        )}
      </div>
    </div>
  )
}
function getTransientStatus(message: ChatMessage): AgentStatusState | null {
  if (message.type === "agent_thinking") {
    return { text: "思考中" }
  }

  if (message.type === "agent_action") {
    return {
      text: message.tool_name
        ? `调用工具中：${message.tool_name}`
        : "调用工具中",
    }
  }

  if (message.type === "agent_tool_result") {
    return {
      text: message.tool_name
        ? `工具已返回，整理结果中：${message.tool_name}`
        : "工具已返回，整理结果中",
    }
  }

  return null
}

function getTerminalSource(source: unknown): TerminalSource | null {
  if (source === "filtered_output" || source === "raw_feedback") {
    return source
  }

  return null
}

function getTerminalSourceLabel(
  source: TerminalSource | null | undefined,
): string | null {
  if (source === "filtered_output") {
    return "过滤输出"
  }

  if (source === "raw_feedback") {
    return "命令反馈"
  }

  return null
}

function getTerminalSourceBadgeClass(
  source: TerminalSource | null | undefined,
): string {
  if (source === "raw_feedback") {
    return "border border-amber-200 bg-amber-50 text-amber-700"
  }

  return "border border-sky-200 bg-sky-50 text-sky-700"
}

function extractSsePayloads(buffer: string): {
  payloads: string[]
  rest: string
} {
  const chunks = buffer.split("\n\n")
  return {
    payloads: chunks.slice(0, -1),
    rest: chunks[chunks.length - 1] ?? "",
  }
}

function readSseData(eventChunk: string): string | null {
  const dataLines = eventChunk
    .split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))

  if (dataLines.length === 0) {
    return null
  }

  return dataLines.join("\n")
}

function isTerminalStreamEvent(event: unknown): boolean {
  if (!event || typeof event !== "object") {
    return false
  }

  const data = event as { done?: unknown; type?: unknown }
  return data.done === true || data.type === "aborted" || data.type === "error"
}

function buildRequestHistory(
  messages: ChatMessage[],
): Array<{ role: "user" | "assistant"; content: string }> {
  return messages.reduce<
    Array<{ role: "user" | "assistant"; content: string }>
  >((history, message) => {
    if (message.localEcho || STATUS_ONLY_TYPES.has(message.type ?? "")) {
      return history
    }

    if (message.role === "user") {
      history.push({ role: "user", content: message.content })
      return history
    }

    if (message.role === "terminal") {
      history.push({
        role: "user",
        content: `终端过滤输出:\n${message.content}`,
      })
      return history
    }

    if (
      message.type &&
      !COMPLETION_TYPES.has(message.type) &&
      message.type !== "chat_assistant"
    ) {
      return history
    }

    history.push({ role: "assistant", content: message.content })
    return history
  }, [])
}

function getMessageLabel(message: ChatMessage): string | null {
  if (message.role === "terminal") {
    return "term"
  }

  if (message.type === "agent_warning") {
    return "警告"
  }

  if (message.type === "agent_error") {
    return "错误"
  }

  return null
}

function getMessageClasses(message: ChatMessage): string {
  if (message.role === "user") {
    return "bg-primary text-primary-foreground"
  }

  if (message.role === "terminal") {
    return "border border-slate-700 bg-slate-950 font-mono text-xs text-emerald-300"
  }

  if (message.type === "agent_error") {
    return "border border-red-300 bg-red-50 text-red-900"
  }

  if (message.type === "agent_warning") {
    return "border border-amber-300 bg-amber-50 text-amber-950"
  }

  return "border bg-muted"
}

export function ChatPanel({ itemId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [handler, setHandler] = useState<ItemHandlerPublic | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [liveError, setLiveError] = useState<string | null>(null)
  const [agentStatus, setAgentStatus] = useState<AgentStatusState | null>(null)
  const [historyHasMore, setHistoryHasMore] = useState(false)
  const [historyTotal, setHistoryTotal] = useState(0)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const suppressNextAutoScrollRef = useRef(false)
  const streamReaderRef =
    useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const canAbortSession =
    Boolean(handler) && (Boolean(agentStatus) || isLoading)

  useEffect(() => {
    if (!agentStatus?.autoClearMs) {
      return
    }

    const timer = window.setTimeout(() => {
      setAgentStatus((current) => (current === agentStatus ? null : current))
    }, agentStatus.autoClearMs)

    return () => window.clearTimeout(timer)
  }, [agentStatus])

  const appendLiveMessage = (message: ChatMessage) => {
    setMessages((prev) => {
      for (let index = prev.length - 1; index >= 0; index -= 1) {
        const current = prev[index]
        if (
          current.localEcho &&
          current.role === "user" &&
          message.type === "chat_user" &&
          current.content === message.content
        ) {
          const next = [...prev]
          next[index] = message
          return next
        }
      }

      const lastMessage = prev[prev.length - 1]
      if (
        lastMessage &&
        lastMessage.role === message.role &&
        lastMessage.type === message.type &&
        lastMessage.timestamp === message.timestamp &&
        lastMessage.content === message.content
      ) {
        return prev
      }

      return [...prev, message]
    })
  }

  const handleIncomingEvent = useEffectEvent((event: unknown) => {
    if (!event || typeof event !== "object") {
      return
    }

    const data = event as {
      done?: unknown
      type?: unknown
      status?: unknown
      content?: unknown
      terminal_source?: unknown
    }

    if (data.done === true) {
      setAgentStatus(null)
      return
    }

    if (data.type === "aborted" || data.type === "error") {
      setAgentStatus(null)
      return
    }

    if (data.type === "agent_status") {
      const status = typeof data.status === "string" ? data.status : ""
      const content = typeof data.content === "string" ? data.content.trim() : ""
      if (!content || TERMINAL_STATUS_DONE_STATES.has(status)) {
        setAgentStatus(null)
        return
      }

      setAgentStatus({
        text: content,
        source: getTerminalSource(data.terminal_source),
        autoClearMs: ACTIVE_AGENT_STATUS_TIMEOUT_MS,
      })
      return
    }
    const normalizedMessage = normalizeMessage(event as Record<string, unknown>)
    if (!normalizedMessage) {
      return
    }

    const transientStatus = getTransientStatus(normalizedMessage)
    if (transientStatus) {
      setAgentStatus({
        ...transientStatus,
        autoClearMs: ACTIVE_AGENT_STATUS_TIMEOUT_MS,
      })
      return
    }
    if (normalizedMessage.type === "chat_user") {
      setAgentStatus({ text: "回复中", autoClearMs: LIVE_REPLY_STATUS_TIMEOUT_MS })
    } else if (
      COMPLETION_TYPES.has(normalizedMessage.type ?? "") ||
      normalizedMessage.role === "assistant"
    ) {
      setAgentStatus(null)
    }

    if (!shouldRenderMessage(normalizedMessage)) {
      return
    }

    appendLiveMessage(normalizedMessage)
  })

  useEffect(() => {
    let cancelled = false

    const fetchData = async () => {
      setHandler(null)
      setMessages([])
      setHistoryError(null)
      setLiveError(null)
      setIsLoading(false)
      setAgentStatus(null)
      setHistoryHasMore(false)
      setHistoryTotal(0)
      setIsLoadingHistory(false)

      const [handlersResult, sessionResult] = await Promise.allSettled([
        ItemHandlerAssociationsService.getHandlersForItem({ itemId }),
        getChatSession(itemId, { limit: CHAT_HISTORY_PAGE_SIZE, offset: 0 }),
      ])

      if (cancelled) {
        return
      }

      if (handlersResult.status === "fulfilled") {
        const handlers = handlersResult.value
        if (handlers && handlers.length > 0) {
          setHandler(handlers[0] as ItemHandlerPublic)
        }
      } else {
        console.error("[Chat] Failed to fetch handler:", handlersResult.reason)
      }

      if (sessionResult.status === "fulfilled") {
        const normalizedMessages = normalizeRenderableMessages(
          sessionResult.value.messages,
        )
        setMessages(normalizedMessages)
        setHistoryTotal(sessionResult.value.total ?? normalizedMessages.length)
        setHistoryHasMore(Boolean(sessionResult.value.has_more))
      } else {
        const errorMessage =
          sessionResult.reason instanceof Error
            ? sessionResult.reason.message
            : String(sessionResult.reason)
        console.error(
          "[Chat] Failed to load session history:",
          sessionResult.reason,
        )
        setHistoryError(`无法读取 SQLite 会话历史: ${errorMessage}`)
      }
    }

    void fetchData()

    return () => {
      cancelled = true
    }
  }, [itemId])

  const loadOlderHistory = async () => {
    if (isLoadingHistory || !historyHasMore) {
      return
    }

    const scrollElement = scrollRef.current
    const previousScrollHeight = scrollElement?.scrollHeight ?? 0
    const previousScrollTop = scrollElement?.scrollTop ?? 0
    const loadedPersistedMessages = messages.filter(
      (message) => !message.localEcho,
    ).length

    setIsLoadingHistory(true)
    try {
      const page = await getChatSession(itemId, {
        limit: CHAT_HISTORY_PAGE_SIZE,
        offset: loadedPersistedMessages,
      })
      const olderMessages = normalizeRenderableMessages(page.messages)
      setHistoryTotal(page.total ?? historyTotal)
      setHistoryHasMore(Boolean(page.has_more))
      suppressNextAutoScrollRef.current = true
      setMessages((current) => {
        const existingKeys = new Set(current.map((message) => getChatMessageKey(message)))
        const uniqueOlderMessages = olderMessages.filter(
          (message) => !existingKeys.has(getChatMessageKey(message)),
        )
        if (uniqueOlderMessages.length === 0) {
          return current
        }
        return [...uniqueOlderMessages, ...current]
      })
      window.requestAnimationFrame(() => {
        const nextScrollElement = scrollRef.current
        if (!nextScrollElement) {
          return
        }
        nextScrollElement.scrollTop =
          nextScrollElement.scrollHeight - previousScrollHeight + previousScrollTop
      })
    } catch (error) {
      console.error("[Chat] Failed to load older session history:", error)
      setHistoryError(
        `加载更早历史失败: ${error instanceof Error ? error.message : String(error)}`,
      )
    } finally {
      setIsLoadingHistory(false)
    }
  }
  useEffect(() => {
    if (!handler) {
      return
    }

    const token = localStorage.getItem("access_token") || ""
    const url = `${OpenAPI.BASE}/api/v1/chat/${itemId}/agent-events`
    let disposed = false
    let reconnectTimer: number | null = null
    let controller: AbortController | null = null
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

    const connect = async () => {
      if (disposed) {
        return
      }

      controller = new AbortController()

      try {
        const response = await fetch(url, {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "text/event-stream",
          },
          signal: controller.signal,
        })

        if (!response.ok) {
          const errorText = await response.text()
          throw new Error(`HTTP ${response.status} ${errorText}`)
        }

        reader = response.body?.getReader() ?? null
        if (!reader) {
          throw new Error("No SSE reader available")
        }

        setLiveError(null)

        const decoder = new TextDecoder()
        let buffer = ""

        while (!disposed) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const { payloads, rest } = extractSsePayloads(buffer)
          buffer = rest

          for (const payload of payloads) {
            const rawEvent = readSseData(payload)
            if (!rawEvent) {
              continue
            }

            try {
              handleIncomingEvent(JSON.parse(rawEvent))
            } catch (error) {
              console.error(
                "[Chat] Failed to parse agent event payload:",
                error,
              )
            }
          }
        }
      } catch (error) {
        if (
          !disposed &&
          !(error instanceof DOMException && error.name === "AbortError")
        ) {
          const message = error instanceof Error ? error.message : String(error)
          console.error("[Chat] Agent event stream error:", error)
          setLiveError(`实时事件连接异常: ${message}`)
        }
      } finally {
        if (reader) {
          reader.cancel().catch(() => undefined)
          reader = null
        }

        if (!disposed) {
          reconnectTimer = window.setTimeout(() => {
            void connect()
          }, 1500)
        }
      }
    }

    void connect()

    return () => {
      disposed = true
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
      }
      controller?.abort()
      if (reader) {
        reader.cancel().catch(() => undefined)
      }
    }
  }, [handler, itemId])

  useEffect(() => {
    const messageCount = messages.length
    if (suppressNextAutoScrollRef.current) {
      suppressNextAutoScrollRef.current = false
      return
    }
    if (scrollRef.current && messageCount >= 0) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages.length])

  const abortChat = async () => {
    const token = localStorage.getItem("access_token") || ""
    setAgentStatus({ text: "中断中" })

    try {
      streamAbortRef.current?.abort()
      streamAbortRef.current = null

      if (streamReaderRef.current) {
        await streamReaderRef.current.cancel()
        streamReaderRef.current = null
      }

      await fetch(`${OpenAPI.BASE}/api/v1/chat/${itemId}/abort`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      })
    } catch (error) {
      console.error("[Chat] Failed to abort:", error)
      setAgentStatus(null)
    } finally {
      setAgentStatus(null)
      setIsLoading(false)
    }
  }

  const sendMessage = async () => {
    const messageText = input.trim()
    if (!messageText || isLoading || !handler) {
      return
    }

    const history = buildRequestHistory(messages)
    setMessages((prev) => [
      ...prev,
      {
        role: "user",
        content: messageText,
        type: "chat_user",
        localEcho: true,
      },
    ])
    setInput("")
    setAgentStatus({ text: "回复中", autoClearMs: LIVE_REPLY_STATUS_TIMEOUT_MS })
    setIsLoading(true)

    const token = localStorage.getItem("access_token") || ""
    const controller = new AbortController()
    streamAbortRef.current = controller

    try {
      const response = await fetch(
        `${OpenAPI.BASE}/api/v1/chat/${itemId}/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          signal: controller.signal,
          body: JSON.stringify({
            message: messageText,
            history,
          }),
        },
      )

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`HTTP ${response.status} ${errorText}`)
      }

      const reader = response.body?.getReader() ?? null
      streamReaderRef.current = reader

      if (!reader) {
        throw new Error("No response reader available")
      }

      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const { payloads, rest } = extractSsePayloads(buffer)
        buffer = rest

        let shouldStop = false

        for (const payload of payloads) {
          const rawEvent = readSseData(payload)
          if (!rawEvent) {
            continue
          }

          try {
            const data = JSON.parse(rawEvent)
            handleIncomingEvent(data)
            if (isTerminalStreamEvent(data)) {
              shouldStop = true
            }
          } catch (error) {
            console.error("[Chat] Failed to parse stream payload:", error)
          }
        }

        if (shouldStop) {
          break
        }
      }

      const trailingEvent = readSseData(buffer)
      if (trailingEvent) {
        try {
          handleIncomingEvent(JSON.parse(trailingEvent))
        } catch (error) {
          console.error("[Chat] Failed to parse trailing stream payload:", error)
        }
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        const errorMessage =
          error instanceof Error ? error.message : String(error)
        console.error("[Chat] Failed to send message:", error)
        setAgentStatus(null)
        appendLiveMessage({
          role: "assistant",
          content: `请求失败: ${errorMessage}`,
          type: "agent_error",
        })
      }
    } finally {
      streamReaderRef.current = null
      streamAbortRef.current = null
      setAgentStatus(null)
      setIsLoading(false)
    }
  }

  const visibleAgentStatus =
    agentStatus ?? (isLoading ? { text: "回复中" } : null)
  const hasConnectionIssue = historyError || liveError

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b bg-background px-4 py-3">
        <div className="flex items-center gap-2">
          {handler ? (
            <Link
              to="/item-handlers/$itemHandlerId"
              params={{ itemHandlerId: handler.id }}
              className="flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary"
            >
              <span>{handler.name}</span>
              <ExternalLink className="size-3" />
            </Link>
          ) : (
            <span className="text-sm text-muted-foreground">
              未关联 ItemHandler
            </span>
          )}
        </div>

        {messages.length > 0 && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="ghost" size="icon" title="清空会话时间线">
                <Trash2 className="size-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>清空会话时间线</AlertDialogTitle>
                <AlertDialogDescription>
                  这会删除当前 item 在 SQLite 里的聊天时间线历史，操作不可撤销。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction
                  onClick={async () => {
                    try {
                      await clearChatSession(itemId)
                      setMessages([])
                      setHistoryError(null)
                      setAgentStatus(null)
                      setHistoryHasMore(false)
                      setHistoryTotal(0)
                    } catch (error) {
                      console.error(
                        "[Chat] Failed to clear chat session:",
                        error,
                      )
                      setHistoryError(
                        `清空会话历史失败: ${error instanceof Error ? error.message : String(error)}`,
                      )
                    }
                  }}
                >
                  确认清空
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      {hasConnectionIssue && (
        <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-950">
          {historyError && <div>{historyError}</div>}
          {liveError && <div>{liveError}</div>}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto" ref={scrollRef}>
        <div className="space-y-3 p-3">
          {messages.length === 0 && (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {handler
                ? "开始与 Agent 对话，或等待终端过滤事件写入时间线。"
                : "关联 ItemHandler 后可启用对话与实时事件。"}
            </div>
          )}

          {messages.length > 0 && historyHasMore && (
            <div className="flex justify-center">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void loadOlderHistory()}
                disabled={isLoadingHistory}
                className="h-7 gap-1.5 px-2 text-xs text-muted-foreground"
                title="向上加载更早的 20 条历史"
              >
                {isLoadingHistory ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ChevronUp className="size-3.5" />
                )}
                <span>
                  {isLoadingHistory ? "加载中" : "加载更早 20 条"}
                  {historyTotal > 0 ? ` · ${messages.length}/${historyTotal}` : ""}
                </span>
              </Button>
            </div>
          )}

          {messages.map((message, index) => {
            const label = getMessageLabel(message)
            const robotDisplay = getRobotMessageDisplay(message)
            const visibleContent = robotDisplay
              ? ""
              : getVisibleChatContent(message)
            const alignment = message.role === "user" ? "justify-end" : "justify-start"
            return (
              <div
                key={`${message.timestamp ?? "msg"}-${index}`}
                className={`flex ${alignment}`}
              >
                {robotDisplay ? (
                  <div className="w-full max-w-[94%]">
                    <RobotMessageCard
                      display={robotDisplay}
                      timestamp={message.timestamp}
                    />
                  </div>
                ) : (
                  <div
                    className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${getMessageClasses(message)}`}
                  >
                    {label && (
                      <div className="mb-1 border-b border-current/15 pb-1 text-[11px] uppercase tracking-wide opacity-70">
                        {label}
                      </div>
                    )}
                    <div
                      className={`whitespace-pre-wrap break-words ${
                        message.role === "terminal" ? "font-mono" : "font-sans"
                      }`}
                    >
                      {visibleContent}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="shrink-0 border-t bg-background px-3 py-3">
        {visibleAgentStatus && (
          <div className="mb-2 flex items-center justify-between gap-3 rounded-md border bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <Loader2 className="size-3.5 animate-spin" />
              <span>{visibleAgentStatus.text}</span>
              {getTerminalSourceLabel(visibleAgentStatus.source) && (
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${getTerminalSourceBadgeClass(visibleAgentStatus.source)}`}
                >
                  {getTerminalSourceLabel(visibleAgentStatus.source)}
                </span>
              )}
            </div>
            {canAbortSession && (
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void abortChat()}
                className="h-7 px-2 text-[11px]"
                title="中断本次会话"
              >
                <Square className="mr-1 size-3" />
                中断本次会话
              </Button>
            )}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                void sendMessage()
              }
            }}
            placeholder={handler ? "输入消息..." : "请先关联 ItemHandler"}
            disabled={isLoading || !handler}
            className="flex-1"
          />
          <Button
            size="icon"
            onClick={() => void sendMessage()}
            disabled={!input.trim() || !handler || isLoading}
          >
            <Send className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
