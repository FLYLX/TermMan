import { useState, useRef, useEffect } from "react"
import { Send, Loader2, ExternalLink, Square } from "lucide-react"
import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { OpenAPI } from "@/client/core/OpenAPI"
import { ItemHandlerAssociationsService } from "@/client"
import type { ItemHandlerPublic } from "@/client"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

interface ChatPanelProps {
  itemId: string
}

async function getChatSession(itemId: string): Promise<{ messages: ChatMessage[] }> {
  const token = localStorage.getItem("access_token") || ""
  const response = await fetch(`${OpenAPI.BASE}/api/v1/memory/${itemId}/session`, {
    headers: { "Authorization": `Bearer ${token}` },
  })
  if (!response.ok) return { messages: [] }
  return response.json()
}

async function saveChatSession(itemId: string, messages: ChatMessage[]): Promise<void> {
  const token = localStorage.getItem("access_token") || ""
  await fetch(`${OpenAPI.BASE}/api/v1/memory/${itemId}/session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify(messages),
  })
}

export function ChatPanel({ itemId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [handler, setHandler] = useState<ItemHandlerPublic | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const handlers = await ItemHandlerAssociationsService.getHandlersForItem({ itemId })
        if (handlers && handlers.length > 0) {
          setHandler(handlers[0])
        }
      } catch (error) {
        console.error("[Chat] Failed to fetch handler:", error)
      }

      try {
        const session = await getChatSession(itemId)
        if (session.messages && session.messages.length > 0) {
          setMessages(session.messages)
        }
      } catch (error) {
        console.error("[Chat] Failed to load session:", error)
      }
    }
    fetchData()
  }, [itemId])

  useEffect(() => {
    if (!handler) return
    
    const token = localStorage.getItem("access_token") || ""
    const url = `${OpenAPI.BASE}/api/v1/chat/${itemId}/agent-events`
    
    let aborted = false
    
    const connect = async () => {
      try {
        const response = await fetch(url, {
          headers: { "Authorization": `Bearer ${token}` },
        })
        
        if (!response.ok || aborted) return
        
        const reader = response.body?.getReader()
        if (!reader) return
        
        const decoder = new TextDecoder()
        
        while (!aborted) {
          const { done, value } = await reader.read()
          if (done) break
          
          const text = decoder.decode(value)
          const lines = text.split("\n\n")
          
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === "agent_response" || data.type === "agent_action" || data.type === "agent_thinking") {
                  setMessages((prev) => {
                    const lastMsg = prev[prev.length - 1]
                    if (lastMsg?.role === "assistant" && lastMsg.content === "") {
                      return [...prev.slice(0, -1), { role: "assistant", content: data.content }]
                    }
                    return [...prev, { role: "assistant", content: data.content }]
                  })
                } else if (data.type === "agent_error") {
                  setMessages((prev) => [
                    ...prev, 
                    { role: "assistant", content: `❌ ${data.content}` }
                  ])
                }
              } catch {
                // Ignore parse errors
              }
            }
          }
        }
      } catch (error) {
        if (!aborted) {
          console.log("[Chat] Agent event source error:", error)
        }
      }
    }
    
    connect()
    
    return () => {
      aborted = true
    }
  }, [itemId, handler])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const abortChat = async () => {
    const token = localStorage.getItem("access_token") || ""
    try {
      if (readerRef.current) {
        readerRef.current.cancel()
        readerRef.current = null
      }
      
      await fetch(`${OpenAPI.BASE}/api/v1/chat/${itemId}/abort`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` },
      })
      setIsLoading(false)
      setMessages((prev) => {
        const newMessages = [...prev]
        const last = newMessages[newMessages.length - 1]
        if (last.role === "assistant" && last.content === "") {
          last.content = "[对话已中断]"
        }
        return newMessages
      })
    } catch (error) {
      console.error("[Chat] Failed to abort:", error)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: ChatMessage = { role: "user", content: input }
    const newMessages = [...messages, userMessage]
    setMessages(newMessages)
    setInput("")
    setIsLoading(true)

    setMessages((prev) => [...prev, { role: "assistant", content: "" }])

    const url = `${OpenAPI.BASE}/api/v1/chat/${itemId}/stream`
    const token = localStorage.getItem("access_token") || ""

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: input,
          history: messages,
        }),
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      const reader = response.body?.getReader()
      readerRef.current = reader
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error("No reader available")
      }

      let fullContent = ""
      let aborted = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value)
        const lines = text.split("\n\n")

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const json = JSON.parse(line.slice(6))
              if (json.type === "aborted") {
                aborted = true
                break
              }
              if (json.content) {
                fullContent += json.content
                setMessages((prev) => {
                  const newMessages = [...prev]
                  const last = newMessages[newMessages.length - 1]
                  if (last.role === "assistant") {
                    last.content = fullContent
                  }
                  return newMessages
                })
              }
              if (json.error) {
                setMessages((prev) => {
                  const newMessages = [...prev]
                  const last = newMessages[newMessages.length - 1]
                  if (last.role === "assistant") {
                    last.content = `Error: ${json.error}`
                  }
                  return newMessages
                })
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
        if (aborted) break
      }

      readerRef.current = null

      const finalMessages = [...newMessages, { role: "assistant" as const, content: fullContent }]
      await saveChatSession(itemId, finalMessages)
    } catch (error) {
      setMessages((prev) => {
        const newMessages = [...prev]
        const last = newMessages[newMessages.length - 1]
        if (last.role === "assistant") {
          last.content = `Error: ${error}`
        }
        return newMessages
      })
    }

    setIsLoading(false)
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b bg-background shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {handler ? (
            <Link
              to="/item-handlers/$itemHandlerId"
              params={{ itemHandlerId: handler.id }}
              className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors"
            >
              <span>{handler.name}</span>
              <ExternalLink className="size-3" />
            </Link>
          ) : (
            <span className="text-sm text-muted-foreground">No Handler</span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto" ref={scrollRef}>
        <div className="p-3 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground text-sm py-8">
              {handler ? "Start a conversation with AI" : "Associate an ItemHandler to enable chat"}
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`px-3 py-2 rounded-lg text-sm max-w-[90%] ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted border"
                }`}
              >
                <div className="whitespace-pre-wrap font-sans break-words">{msg.content}</div>
              </div>
            </div>
          ))}

          {isLoading && messages[messages.length - 1]?.content === "" && (
            <div className="flex justify-start">
              <div className="bg-muted border px-3 py-2 rounded-lg">
                <Loader2 className="size-4 animate-spin" />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="px-3 py-3 border-t bg-background shrink-0">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                sendMessage()
              }
            }}
            placeholder="Type a message..."
            disabled={isLoading || !handler}
            className="flex-1"
          />
          {isLoading ? (
            <Button
              size="icon"
              variant="destructive"
              onClick={abortChat}
              title="停止对话"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={sendMessage}
              disabled={!input.trim() || !handler}
            >
              <Send className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
