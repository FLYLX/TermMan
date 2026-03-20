import { useCallback, useEffect, useRef, useState } from "react"
import { io, Socket } from "socket.io-client"
import { ItemsService } from "@/client"

interface TerminalOutput {
  stdout?: string
  stderr?: string
  stdin?: string
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
  reconnect: () => void
  disconnect: () => void
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
  const reconnectAttemptRef = useRef(0)
  const connectingRef = useRef(false)
  const maxReconnectAttempts = 3
  
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

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect()
      socketRef.current = null
    }
    setIsConnected(false)
    setIsConnecting(false)
    connectingRef.current = false
  }, [])

  const connect = useCallback(async () => {
    if (!enabled || !itemId || connectingRef.current) return

    connectingRef.current = true
    setIsConnecting(true)
    setError(null)

    try {
      const tokenData = await ItemsService.getTerminalToken({ id: itemId })
      
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

      socketRef.current = socket

      socket.on("connect", () => {
        console.log("[Terminal] Socket connected")
      })

      socket.on("terminal_connected", (data: TerminalConnectedData) => {
        console.log("[Terminal] Terminal connected:", data)
        setIsConnected(true)
        setIsConnecting(false)
        connectingRef.current = false
        reconnectAttemptRef.current = 0
        onConnectedRef.current?.(data)
      })

      socket.on("auth_error", (data: { message: string }) => {
        console.error("[Terminal] Auth error:", data.message)
        setError(data.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(data.message)
        socket.disconnect()
      })

      socket.on("stream", (data: TerminalOutput) => {
        setOutput((prev) => [...prev, data])
      })

      socket.on("disconnect", (reason) => {
        console.log("[Terminal] Disconnected:", reason)
        setIsConnected(false)
        setIsConnecting(false)
        connectingRef.current = false
        onDisconnectedRef.current?.()
      })

      socket.on("connect_error", (err) => {
        console.error("[Terminal] Connect error:", err.message)
        setError(err.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(err.message)
      })

    } catch (err) {
      console.error("[Terminal] Connection error:", err)
      const errorMessage = err instanceof Error ? err.message : "Connection failed"
      setError(errorMessage)
      setIsConnecting(false)
      connectingRef.current = false
      onErrorRef.current?.(errorMessage)
    }
  }, [enabled, itemId])

  const reconnect = useCallback(() => {
    if (reconnectAttemptRef.current < maxReconnectAttempts) {
      reconnectAttemptRef.current++
      console.log(`[Terminal] Reconnecting... Attempt ${reconnectAttemptRef.current}`)
      disconnect()
      setTimeout(connect, 1000)
    } else {
      setError("Max reconnection attempts reached")
    }
  }, [connect, disconnect])

  const sendCommand = useCallback((command: string) => {
    if (socketRef.current && isConnected) {
      socketRef.current.emit("terminal/write", { command })
    }
  }, [isConnected])

  useEffect(() => {
    if (enabled && itemId) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, itemId])

  return {
    isConnected,
    isConnecting,
    error,
    output,
    clearOutput,
    sendCommand,
    reconnect,
    disconnect,
  }
}
