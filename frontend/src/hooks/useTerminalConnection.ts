import { useCallback, useEffect, useRef, useState } from "react"
import { io, Socket } from "socket.io-client"
import { ItemsService } from "@/client"

interface TerminalOutput {
  stdout?: string
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
  sendCtrlC: () => void
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

  const disconnect = useCallback(() => {
    const socket = socketRef.current
    if (socket) {
      socket.removeAllListeners()
      socket.disconnect()
      socketRef.current = null
    }
    setIsConnected(false)
    setIsConnecting(false)
    connectingRef.current = false
  }, [])

  const doConnect = useCallback(async () => {
    if (!enabled || !itemId) {
      return
    }
    
    if (connectingRef.current) {
      return
    }
    
    if (socketRef.current) {
      return
    }

    const currentConnectionId = ++connectionIdRef.current
    connectingRef.current = true
    setIsConnecting(true)
    setError(null)

    try {
      const outputData = await ItemsService.getItemOutput({ id: itemId }) as {
        success: boolean
        output: string | null
      }
      if (outputData.success && outputData.output) {
        const lines = outputData.output.split('\n')
        const outputLines = lines.filter(line => line.trim()).map(line => ({ stdout: line + '\n' }))
        setOutput(outputLines)
      }
      
      if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
        return
      }
      
      const tokenData = await ItemsService.getTerminalToken({ id: itemId })
      
      if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
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

      if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
        socket.removeAllListeners()
        socket.disconnect()
        return
      }

      socketRef.current = socket

      socket.on("connect", () => {
        console.log("[Terminal] Socket connected")
      })

      socket.on("terminal_connected", (data: TerminalConnectedData) => {
        if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
          return
        }
        console.log("[Terminal] Terminal connected:", data)
        setIsConnected(true)
        setIsConnecting(false)
        connectingRef.current = false
        onConnectedRef.current?.(data)
      })

      socket.on("auth_error", (data: { message: string }) => {
        if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
          return
        }
        console.error("[Terminal] Auth error:", data.message)
        setError(data.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(data.message)
        socket.disconnect()
      })

      socket.on("stream", (data: TerminalOutput) => {
        if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
          return
        }
        setOutput((prev) => [...prev, data])
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
        if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
          return
        }
        console.error("[Terminal] Connect error:", err.message)
        setError(err.message)
        setIsConnecting(false)
        connectingRef.current = false
        onErrorRef.current?.(err.message)
      })

    } catch (err) {
      if (!mountedRef.current || currentConnectionId !== connectionIdRef.current) {
        return
      }
      console.error("[Terminal] Connection error:", err)
      const errorMessage = err instanceof Error ? err.message : "Connection failed"
      setError(errorMessage)
      setIsConnecting(false)
      connectingRef.current = false
      onErrorRef.current?.(errorMessage)
    }
  }, [enabled, itemId])

  const reconnect = useCallback(() => {
    disconnect()
    connectionIdRef.current++
    setTimeout(() => {
      if (mountedRef.current) {
        doConnect()
      }
    }, 300)
  }, [doConnect, disconnect])

  const sendCommand = useCallback((command: string) => {
    if (socketRef.current && isConnected) {
      socketRef.current.emit("terminal/write", { command })
    }
  }, [isConnected])

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
      if (socket) {
        socket.removeAllListeners()
        socket.disconnect()
        socketRef.current = null
      }
      connectingRef.current = false
    }
  }, [enabled, itemId])

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
