import { Link } from "@tanstack/react-router"
import { ExternalLink, Loader2, Send, Square, Trash2 } from "lucide-react"
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

async function getChatSession(
  itemId: string,
): Promise<{ messages: ChatMessage[] }> {
  const token = localStorage.getItem("access_token") || ""
  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/memory/${itemId}/session`,
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

  const scrollRef = useRef<HTMLDivElement>(null)
  const streamReaderRef =
    useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const canAbortSession =
    Boolean(handler) && (Boolean(agentStatus) || isLoading)

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
      if (data.status === "idle") {
        setAgentStatus(null)
        return
      }

      if (typeof data.content === "string" && data.content.trim()) {
        setAgentStatus({
          text: data.content,
          source: getTerminalSource(data.terminal_source),
        })
      }
      return
    }

    const normalizedMessage = normalizeMessage(event as Record<string, unknown>)
    if (!normalizedMessage) {
      return
    }

    const transientStatus = getTransientStatus(normalizedMessage)
    if (transientStatus) {
      setAgentStatus(transientStatus)
      return
    }

    if (normalizedMessage.type === "chat_user") {
      setAgentStatus({ text: "回复中" })
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

      const [handlersResult, sessionResult] = await Promise.allSettled([
        ItemHandlerAssociationsService.getHandlersForItem({ itemId }),
        getChatSession(itemId),
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
        const normalizedMessages = (sessionResult.value.messages ?? [])
          .map((message) => normalizeMessage(message))
          .filter(
            (message): message is ChatMessage =>
              message !== null && shouldRenderMessage(message),
          )
        setMessages(normalizedMessages)
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
    setAgentStatus({ text: "回复中" })
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
            if (data.done || data.type === "aborted" || data.type === "error") {
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
      setIsLoading(false)
    }
  }

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

          {messages.map((message, index) => {
            const label = getMessageLabel(message)
            return (
              <div
                key={`${message.timestamp ?? "msg"}-${index}`}
                className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
              >
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
                    {message.content}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="shrink-0 border-t bg-background px-3 py-3">
        {agentStatus && (
          <div className="mb-2 flex items-center justify-between gap-3 rounded-md border bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <Loader2 className="size-3.5 animate-spin" />
              <span>{agentStatus.text}</span>
              {getTerminalSourceLabel(agentStatus.source) && (
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${getTerminalSourceBadgeClass(agentStatus.source)}`}
                >
                  {getTerminalSourceLabel(agentStatus.source)}
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
