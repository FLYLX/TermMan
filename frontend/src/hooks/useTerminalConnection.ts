import { useCallback, useEffect, useRef, useState } from "react"
import { io, type Socket } from "socket.io-client"
import { ItemsService } from "@/client"

export interface TerminalOutput {
  stdout?: string
  stderr?: string
  stdin?: string
  source?: string
  status?: string
  job_id?: string
  exit_code?: number
  timed_out?: boolean
  cancelled?: boolean
}

interface RoomInfo {
  permanent_count: number
  temporary_count: number
}

interface TerminalConnectedData {
  item_uuid: string
  subscriber_type: string
  room_info: RoomInfo
  user_uuid?: string
}

interface UseTerminalConnectionOptions {
  itemId: string
  enabled?: boolean
  onConnected?: (data: TerminalConnectedData) => void
  onDisconnected?: () => void
  onError?: (error: string) => void
}

interface UseTerminalConnectionReturn {
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  output: TerminalOutput[]
  clearOutput: () => void
  sendCommand: (command: string) => void
  sendCtrlC: () => void
  reconnect: (force?: boolean) => void
  disconnect: () => void
}

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const ANSI_ESCAPE_RE = new RegExp(
  `${ESC}(?:\\[[0-?]*[ -/]*[@-~]|\\][^${BEL}]*(?:${BEL}|${ESC}\\\\)|[PX^_].*?${ESC}\\\\|[@-Z\\\\-_=>])`,
  "g",
)
const PROMPT_BEFORE_TIMESTAMP_RE = /^(?:\s*[>#]\s*)+(?=\[\d{2}:\d{2}:\d{2}\])/gm

function stripTerminalControlChars(text: string): string {
  let result = ""
  for (const char of text) {
    const code = char.charCodeAt(0)
    if (
      code <= 7 ||
      code === 11 ||
      code === 12 ||
      (code >= 14 && code <= 31) ||
      code === 127
    ) {
      continue
    }
    result += char
  }
  return result
}

function sanitizeTerminalText(value: unknown): string {
  const text = String(value ?? "")
  if (!text) {
    return ""
  }
  return stripTerminalControlChars(text.replace(ANSI_ESCAPE_RE, "")).replace(
    PROMPT_BEFORE_TIMESTAMP_RE,
    "",
  )
}

function sanitizeTerminalOutput(entry: TerminalOutput): TerminalOutput {
  return {
    ...entry,
    stdout:
      typeof entry.stdout === "string"
        ? sanitizeTerminalText(entry.stdout)
        : entry.stdout,
    stderr:
      typeof entry.stderr === "string"
        ? sanitizeTerminalText(entry.stderr)
        : entry.stderr,
    stdin:
      typeof entry.stdin === "string"
        ? sanitizeTerminalText(entry.stdin)
        : entry.stdin,
  }
}

function getOutputText(entry: TerminalOutput): {
  key: "stdout" | "stderr" | "stdin"
  text: string
} | null {
  if (typeof entry.stdout === "string") {
    return { key: "stdout", text: entry.stdout }
  }
  if (typeof entry.stderr === "string") {
    return { key: "stderr", text: entry.stderr }
  }
  if (typeof entry.stdin === "string") {
    return { key: "stdin", text: entry.stdin }
  }
  return null
}

function replaceOutputText(
  entry: TerminalOutput,
  key: "stdout" | "stderr" | "stdin",
  text: string,
): TerminalOutput {
  return { ...entry, [key]: text }
}

function trimCurrentTerminalLine(entries: TerminalOutput[]): void {
  while (entries.length > 0) {
    const lastIndex = entries.length - 1
    const current = getOutputText(entries[lastIndex])
    if (!current) {
      entries.pop()
      continue
    }

    const newlineIndex = current.text.lastIndexOf("\n")
    if (newlineIndex >= 0) {
      const kept = current.text.slice(0, newlineIndex + 1)
      if (kept) {
        entries[lastIndex] = replaceOutputText(
          entries[lastIndex],
          current.key,
          kept,
        )
      } else {
        entries.pop()
      }
      return
    }

    entries.pop()
  }
}

function removeLastTerminalChar(entries: TerminalOutput[]): void {
  while (entries.length > 0) {
    const lastIndex = entries.length - 1
    const current = getOutputText(entries[lastIndex])
    if (!current) {
      entries.pop()
      continue
    }

    if (current.text.length <= 1) {
      entries.pop()
      return
    }

    entries[lastIndex] = replaceOutputText(
      entries[lastIndex],
      current.key,
      current.text.slice(0, -1),
    )
    return
  }
}

function appendTerminalText(
  entries: TerminalOutput[],
  key: "stdout" | "stderr" | "stdin",
  text: string,
  metadata: TerminalOutput,
): void {
  let buffer = ""

  const flush = () => {
    if (!buffer) {
      return
    }
    entries.push({ ...metadata, [key]: buffer })
    buffer = ""
  }

  for (const char of text) {
    if (char === "\r") {
      flush()
      trimCurrentTerminalLine(entries)
      continue
    }

    if (char === "\b") {
      flush()
      removeLastTerminalChar(entries)
      continue
    }

    buffer += char
  }

  flush()
}

function appendTerminalOutput(
  previous: TerminalOutput[],
  incoming: TerminalOutput,
): TerminalOutput[] {
  const sanitizedIncoming = sanitizeTerminalOutput(incoming)
  const textFields = [
    ["stdin", sanitizedIncoming.stdin],
    ["stdout", sanitizedIncoming.stdout],
    ["stderr", sanitizedIncoming.stderr],
  ] as const
  const hasControl = textFields.some(
    ([, value]) =>
      typeof value === "string" &&
      (value.includes("\r") || value.includes("\b")),
  )

  if (!hasControl) {
    return [...previous, sanitizedIncoming]
  }

  const next = [...previous]
  const metadata = {
    source: sanitizedIncoming.source,
    status: sanitizedIncoming.status,
    job_id: sanitizedIncoming.job_id,
    exit_code: sanitizedIncoming.exit_code,
    timed_out: sanitizedIncoming.timed_out,
    cancelled: sanitizedIncoming.cancelled,
  }

  for (const [key, value] of textFields) {
    if (typeof value === "string" && value) {
      appendTerminalText(next, key, value, metadata)
    }
  }

  return next
}

export function useTerminalConnection({
  itemId,
  enabled = true,
  onConnected,
  onDisconnected,
  onError,
}: UseTerminalConnectionOptions): UseTerminalConnectionReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [output, setOutput] = useState<TerminalOutput[]>([])

  const socketRef = useRef<Socket | null>(null)
  const connectingRef = useRef(false)
  const mountedRef = useRef(true)
  const connectionIdRef = useRef(0)

  const onConnectedRef = useRef(onConnected)
  const onDisconnectedRef = useRef(onDisconnected)
  const onErrorRef = useRef(onError)

  useEffect(() => {
    onConnectedRef.current = onConnected
    onDisconnectedRef.current = onDisconnected
    onErrorRef.current = onError
  }, [onConnected, onDisconnected, onError])

  const clearOutput = useCallback(() => {
    setOutput([])
  }, [])

  const disposeSocket = useCallback((socket: Socket | null) => {
    if (!socket) {
      return
    }
    socket.removeAllListeners()
    socket.disconnect()
    if (socketRef.current === socket) {
      socketRef.current = null
    }
  }, [])

  const disconnect = useCallback(() => {
    const socket = socketRef.current
    disposeSocket(socket)
    setIsConnected(false)
    setIsConnecting(false)
    connectingRef.current = false
  }, [disposeSocket])

  const doConnect = useCallback(async (force = false) => {
    if ((!force && !enabled) || !itemId) {
      return
    }

    if (connectingRef.current) {
      return
    }

    const existingSocket = socketRef.current
    if (existingSocket) {
      if (existingSocket.connected) {
        return
      }
      disposeSocket(existingSocket)
    }

    const currentConnectionId = ++connectionIdRef.current
    connectingRef.current = true
    setIsConnecting(true)
    setError(null)

    try {
      const outputData = (await ItemsService.getItemOutput({ id: itemId })) as {
        success: boolean
        output: string | null
      }
      if (outputData.success && outputData.output) {
        const lines = sanitizeTerminalText(outputData.output).split("\n")
        const outputLines = lines
          .filter((line) => line.trim())
          .map((line) => ({ stdout: `${line}\n` }))
        setOutput(outputLines)
      }

      if (
        !mountedRef.current ||
        currentConnectionId !== connectionIdRef.current
      ) {
        return
      }

      const tokenData = await ItemsService.getTerminalToken({ id: itemId })

      if (
        !mountedRef.current ||
        currentConnectionId !== connectionIdRef.current
      ) {
        return
      }

      if (!tokenData.success) {
        throw new Error("Failed to get terminal token")
      }

      const { temp_token, ws_url, item_uuid } = tokenData as {
        temp_token: string
        ws_url: string
        item_uuid: string
      }

      const socket = io(ws_url, {
        transports: ["websocket"],
        auth: {
          temp_token,
          item_uuid,
        },
        reconnection: false,
      })

      if (
        !mountedRef.current ||
        currentConnectionId !== connectionIdRef.current
      ) {
        socket.removeAllListeners()
        socket.disconnect()
        return
      }

      socketRef.current = socket

      socket.on("connect", () => {
        console.log("[Terminal] Socket connected")
      })

      socket.on("terminal_connected", (data: TerminalConnectedData) => {
        if (
          !mountedRef.current ||
          currentConnectionId !== connectionIdRef.current
        ) {
          return
        }
        console.log("[Terminal] Terminal connected:", data)
        setIsConnected(true)
        setIsConnecting(false)
        connectingRef.current = false
        onConnectedRef.current?.(data)
      })

      socket.on("auth_error", (data: { message: string }) => {
        if (
          !mountedRef.current ||
          currentConnectionId !== connectionIdRef.current
        ) {
          return
        }
        console.error("[Terminal] Auth error:", data.message)
        setError(data.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(data.message)
        disposeSocket(socket)
      })

      socket.on("stream", (data: TerminalOutput) => {
        if (
          !mountedRef.current ||
          currentConnectionId !== connectionIdRef.current
        ) {
          return
        }
        setOutput((prev) => appendTerminalOutput(prev, data))
      })

      socket.on("disconnect", (reason) => {
        console.log("[Terminal] Disconnected:", reason)
        if (socketRef.current === socket) {
          setIsConnected(false)
          setIsConnecting(false)
          connectingRef.current = false
          socketRef.current = null
          onDisconnectedRef.current?.()
        }
      })

      socket.on("connect_error", (err) => {
        if (
          !mountedRef.current ||
          currentConnectionId !== connectionIdRef.current
        ) {
          return
        }
        console.error("[Terminal] Connect error:", err.message)
        setError(err.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(err.message)
        disposeSocket(socket)
      })
    } catch (err) {
      if (
        !mountedRef.current ||
        currentConnectionId !== connectionIdRef.current
      ) {
        return
      }
      console.error("[Terminal] Connection error:", err)
      const errorMessage =
        err instanceof Error ? err.message : "Connection failed"
      setError(errorMessage)
      setIsConnecting(false)
      connectingRef.current = false
      onErrorRef.current?.(errorMessage)
    }
  }, [disposeSocket, enabled, itemId])

  const reconnect = useCallback((force = false) => {
    disconnect()
    connectionIdRef.current++
    setTimeout(() => {
      if (mountedRef.current) {
        doConnect(force)
      }
    }, 300)
  }, [doConnect, disconnect])

  const sendCommand = useCallback(
    (command: string) => {
      if (socketRef.current && isConnected) {
        socketRef.current.emit("terminal/write", { command })
      }
    },
    [isConnected],
  )

  const sendCtrlC = useCallback(() => {
    if (socketRef.current && isConnected) {
      socketRef.current.emit("terminal/write", { command: "\x03" })
    }
  }, [isConnected])

  useEffect(() => {
    mountedRef.current = true

    if (enabled && itemId) {
      doConnect()
    }

    return () => {
      mountedRef.current = false
      connectionIdRef.current++
      const socket = socketRef.current
      disposeSocket(socket)
      connectingRef.current = false
    }
  }, [disposeSocket, enabled, itemId, doConnect])

  return {
    isConnected,
    isConnecting,
    error,
    output,
    clearOutput,
    sendCommand,
    sendCtrlC,
    reconnect,
    disconnect,
  }
}
