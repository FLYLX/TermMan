import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronRight,
  Copy,
  Filter,
  Loader2,
  Play,
  Plug,
  Save,
  Send,
  Shield,
  Terminal,
  Users,
  WifiOff,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { ApiError, type ItemPublic, type ItemUpdate, ItemsService } from "@/client"
import {
  createFallbackItem,
  getStoredItemSnapshot,
  saveItemSnapshot,
} from "@/components/Items/itemDetailSnapshots"
import { FilterRuleEditor, type FilterRule } from "@/components/Items/FilterRuleEditor"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { useTerminalConnection } from "@/hooks/useTerminalConnection"

type ItemWithExtras = ItemPublic & {
  daemon_url?: string
  daemon_id?: string
  daemon_online?: boolean
  daemon_status?: string
  connected_users?: Record<string, { user_uuid: string; ip: string }>
  token?: string
}

type ItemsResponse = {
  data: ItemWithExtras[]
  count: number
}

function getItemQueryOptions(itemId: string) {
  return {
    queryFn: () => ItemsService.readItem({ id: itemId }),
    queryKey: ["items", "detail", itemId],
    refetchOnWindowFocus: false,
    retry: false,
  }
}

function getCachedItem(items: ItemsResponse | undefined, itemId: string) {
  return items?.data.find((item: ItemWithExtras) => item.id === itemId)
}

function formatDate(value?: string | null) {
  if (!value) {
    return "N/A"
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function getErrorMessage(error: Error | null) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: string })?.detail
    if (detail) {
      return detail
    }
  }

  return error?.message || "Unable to load item details right now."
}

function CopyValue({ label, value }: { label: string; value?: string | null }) {
  const [copiedText, copy] = useCopyToClipboard()
  const displayValue = value || "N/A"
  const isCopied = copiedText === displayValue

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm">{displayValue}</span>
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={() => copy(displayValue)}
          >
            {isCopied ? (
              <Check className="size-3 text-green-500" />
            ) : (
              <Copy className="size-3" />
            )}
            <span className="sr-only">Copy {label}</span>
          </Button>
        )}
      </div>
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">{value || "N/A"}</span>
    </div>
  )
}

function getStatusBadge(status?: string) {
  switch (status) {
    case "running":
      return (
        <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
          Running
        </Badge>
      )
    case "starting":
      return (
        <Badge className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
          Starting
        </Badge>
      )
    case "stopping":
      return (
        <Badge className="border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400">
          Stopping
        </Badge>
      )
    case "stopped":
      return <Badge variant="secondary">Stopped</Badge>
    case "error":
      return (
        <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
          Error
        </Badge>
      )
    default:
      return <Badge variant="outline">Unknown</Badge>
  }
}

function ItemDetailPage({
  item,
  isUsingFallback,
  message,
}: {
  item: ItemWithExtras
  isUsingFallback: boolean
  message?: string
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [command, setCommand] = useState("")
  const outputRef = useRef<HTMLDivElement>(null)

  const [isSavingInputFilter, setIsSavingInputFilter] = useState(false)
  const [isSavingOutputFilter, setIsSavingOutputFilter] = useState(false)
  
  const defaultInputRules = {
    block_filter: {
      regex_patterns: [
        "violence|porn|gambling",
        "http://.*\\.exe",
      ],
      action_type: "block"
    },
    ignore_filter: {
      regex_patterns: [
        "^\\s*$",
        "^\\x1b\\[[0-9;]*[a-zA-Z]$",
        "^\\r$",
        "\\d+%",
        "\\[\\s*=+\\s*\\]",
        "\\.\\.\\.+",
        "DEBUG\\s*:",
        "INFO\\s*:",
      ],
      action_type: "ignore"
    },
    log_filter: {
      regex_patterns: [
        "error:",
        "failed:",
        "exception:",
        "Error:",
        "FAILED",
        "EXCEPTION",
        "warning:",
        "warn:",
        "Warning:",
        "WARN",
        "\\(y/n\\)",
        "\\[Y/n\\]",
        "enter.*:",
        "password:",
        "confirm",
      ],
      action_type: "log"
    },
    replace_filter: {
      regex_patterns: [
        "^\\d{11}$",
        "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
      ],
      action_type: "replace",
      action: {
        replace_rules: {
          "^\\d{11}$": "***phone***",
          "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}": "***email***"
        }
      }
    }
  }

  const defaultOutputRules = {
    block_filter: {
      regex_patterns: [
        "rm\\s+-rf\\s+/",
        "rm\\s+-rf\\s+~",
        "mkfs",
        "dd\\s+if=",
        ">\\s*/dev/sd",
        ":\\(\\)\\s*\\{\\s*:\\|\\:&\\s*\\}\\s*;:",
        "chmod\\s+777\\s+/",
        "chown\\s+.*:.*\\s+/",
        "shutdown",
        "reboot",
        "init\\s+0",
        "init\\s+6",
        "halt",
        "poweroff",
      ],
      action_type: "block"
    },
    ignore_filter: {
      regex_patterns: [
        "DEBUG\\s*:",
        "INFO\\s*:",
      ],
      action_type: "ignore"
    },
    log_filter: {
      regex_patterns: [
        "sudo\\s+",
        "chmod\\s+",
        "chown\\s+",
      ],
      action_type: "log"
    },
    replace_filter: {
      regex_patterns: [
        "password\\s*=\\s*\\S+",
        "api[_-]?key\\s*=\\s*\\S+",
        "secret\\s*=\\s*\\S+",
        "token\\s*=\\s*\\S+",
        "--password\\s+\\S+",
        "-p\\s+\\S+",
      ],
      action_type: "replace",
      action: {
        replace_rules: {
          "password\\s*=\\s*\\S+": "password=***",
          "api[_-]?key\\s*=\\s*\\S+": "api_key=***",
          "secret\\s*=\\s*\\S+": "secret=***",
          "token\\s*=\\s*\\S+": "token=***",
          "--password\\s+\\S+": "--password ***",
          "-p\\s+\\S+": "-p ***"
        }
      }
    }
  }

  const [inputFilterEnabled, setInputFilterEnabled] = useState(item.input_filter_enabled || false)
  const [inputFilterRules, setInputFilterRules] = useState<Record<string, FilterRule>>(
    item.input_filter_rules && Object.keys(item.input_filter_rules).length > 0
      ? item.input_filter_rules as Record<string, FilterRule>
      : defaultInputRules as Record<string, FilterRule>
  )

  const [outputFilterEnabled, setOutputFilterEnabled] = useState(item.output_filter_enabled || false)
  const [outputFilterRules, setOutputFilterRules] = useState<Record<string, FilterRule>>(
    item.output_filter_rules && Object.keys(item.output_filter_rules).length > 0
      ? item.output_filter_rules as Record<string, FilterRule>
      : defaultOutputRules as Record<string, FilterRule>
  )

  const [inputTestText, setInputTestText] = useState("")
  const [inputTestResult, setInputTestResult] = useState<Record<string, unknown> | null>(null)
  const [isTestingInputFilter, setIsTestingInputFilter] = useState(false)

  const [outputTestCommand, setOutputTestCommand] = useState("")
  const [outputTestResult, setOutputTestResult] = useState<Record<string, unknown> | null>(null)
  const [isTestingOutputFilter, setIsTestingOutputFilter] = useState(false)

  useEffect(() => {
    setInputFilterEnabled(item.input_filter_enabled || false)
    setInputFilterRules(
      item.input_filter_rules && Object.keys(item.input_filter_rules).length > 0
        ? item.input_filter_rules as Record<string, FilterRule>
        : defaultInputRules as Record<string, FilterRule>
    )
    setOutputFilterEnabled(item.output_filter_enabled || false)
    setOutputFilterRules(
      item.output_filter_rules && Object.keys(item.output_filter_rules).length > 0
        ? item.output_filter_rules as Record<string, FilterRule>
        : defaultOutputRules as Record<string, FilterRule>
    )
  }, [item])

  const shouldConnect = item.status === "running" && item.daemon_online

  const {
    isConnected,
    isConnecting,
    error: connectionError,
    output,
    sendCommand,
    sendCtrlC,
    reconnect,
    disconnect,
  } = useTerminalConnection({
    itemId: item.id,
    enabled: shouldConnect,
    onConnected: (data) => {
      console.log("[Terminal] Connected:", data)
      showSuccessToast("Terminal connected")
    },
    onDisconnected: () => {
      console.log("[Terminal] Disconnected")
    },
    onError: (error) => {
      console.error("[Terminal] Error:", error)
      showErrorToast(`Terminal error: ${error}`)
    },
  })

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [])

  const handleStartItem = async () => {
    try {
      const result = await ItemsService.startItem({ id: item.id })
      queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || "Item started successfully")
    } catch (error) {
      console.error("Failed to start item:", error)
      showErrorToast("Failed to start item")
    }
  }

  const handleStopItem = async () => {
    try {
      disconnect()
      const result = await ItemsService.stopItem({ id: item.id })
      queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || "Item stopped successfully")
    } catch (error) {
      console.error("Failed to stop item:", error)
      showErrorToast("Failed to stop item")
    }
  }

  const handleRestartItem = async () => {
    try {
      disconnect()
      const result = await ItemsService.restartItem({ id: item.id })
      await queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || "Item restarted successfully")
      reconnect()
    } catch (error) {
      console.error("Failed to restart item:", error)
      showErrorToast("Failed to restart item")
    }
  }

  const handleSendCommand = () => {
    if (command.trim()) {
      sendCommand(command)
      setCommand("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendCommand()
    }
  }

  const handleSaveInputFilter = async () => {
    setIsSavingInputFilter(true)
    try {
      const updateData: ItemUpdate = {
        input_filter_enabled: inputFilterEnabled,
        input_filter_rules: inputFilterRules,
      }

      await ItemsService.updateItem({ id: item.id, requestBody: updateData })
      queryClient.invalidateQueries({ queryKey: ["items", "detail", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast("Input filter saved successfully")
    } catch (error) {
      console.error("Failed to save input filter:", error)
      showErrorToast("Failed to save input filter")
    } finally {
      setIsSavingInputFilter(false)
    }
  }

  const handleSaveOutputFilter = async () => {
    setIsSavingOutputFilter(true)
    try {
      const updateData: ItemUpdate = {
        output_filter_enabled: outputFilterEnabled,
        output_filter_rules: outputFilterRules,
      }

      await ItemsService.updateItem({ id: item.id, requestBody: updateData })
      queryClient.invalidateQueries({ queryKey: ["items", "detail", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast("Output filter saved successfully")
    } catch (error) {
      console.error("Failed to save output filter:", error)
      showErrorToast("Failed to save output filter")
    } finally {
      setIsSavingOutputFilter(false)
    }
  }

  const handleTestInputFilter = async () => {
    if (!inputTestText.trim()) {
      showErrorToast("Please enter test text")
      return
    }
    setIsTestingInputFilter(true)
    try {
      const result = await ItemsService.testInputFilter({
        id: item.id,
        requestBody: { test_text: inputTestText }
      })
      setInputTestResult(result)
    } catch (error) {
      console.error("Failed to test input filter:", error)
      showErrorToast("Failed to test input filter")
    } finally {
      setIsTestingInputFilter(false)
    }
  }

  const handleTestOutputFilter = async () => {
    if (!outputTestCommand.trim()) {
      showErrorToast("Please enter a command to test")
      return
    }
    setIsTestingOutputFilter(true)
    try {
      const result = await ItemsService.testOutputFilter({
        id: item.id,
        requestBody: { command: outputTestCommand }
      })
      setOutputTestResult(result)
    } catch (error) {
      console.error("Failed to test output filter:", error)
      showErrorToast("Failed to test output filter")
    } finally {
      setIsTestingOutputFilter(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-6">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Link to="/items" className="hover:text-foreground">
            Items
          </Link>
          <ChevronRight className="size-4" />
          <span className="text-foreground">Terminal</span>
        </div>

        <div className="rounded-2xl border bg-card/85 px-5 py-5 shadow-sm">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex flex-col gap-4">
              <Button
                asChild
                variant="outline"
                size="sm"
                className="h-8 w-fit px-3"
              >
                <Link to="/items">
                  <ArrowLeft className="size-4" />
                  Back to items
                </Link>
              </Button>

              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <div className="flex size-12 items-center justify-center rounded-xl border bg-muted/40">
                  <Terminal className="size-6 text-muted-foreground" />
                </div>

                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="text-3xl font-bold tracking-tight">
                      {item.title}
                    </h1>
                    {getStatusBadge(item.status)}
                    {isUsingFallback && (
                      <Badge variant="secondary">Fallback Mode</Badge>
                    )}
                  </div>

                  <p className="max-w-3xl text-sm text-muted-foreground">
                    {item.description || "No description"}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                className="h-10 px-4"
                onClick={handleStartItem}
              >
                Start
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-10 px-4"
                onClick={handleStopItem}
              >
                Stop
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-10 px-4"
                onClick={handleRestartItem}
              >
                Restart
              </Button>
            </div>
          </div>

          {isUsingFallback && (
            <div className="mt-5 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm">
              <div className="flex items-center gap-2">
                <AlertCircle className="size-4 text-yellow-600 dark:text-yellow-400" />
                <span className="font-medium text-yellow-600 dark:text-yellow-400">
                  {message || "Rendering with cached or placeholder data"}
                </span>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold">Terminal</h2>
              <p className="text-sm text-muted-foreground">
                Real-time console output and command input
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {isConnecting ? (
                <Badge
                  variant="outline"
                  className="border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                >
                  <Loader2 className="size-3 mr-1 animate-spin" />
                  Connecting...
                </Badge>
              ) : isConnected ? (
                <>
                  <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
                    Connected
                  </Badge>
                  <Badge variant="secondary">Realtime Console</Badge>
                </>
              ) : connectionError ? (
                <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
                  <AlertCircle className="size-3 mr-1" />
                  Error
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
                >
                  <WifiOff className="size-3 mr-1" />
                  Disconnected
                </Badge>
              )}
            </div>
          </div>

          <div className="rounded-2xl border bg-[#151515] p-4 shadow-inner">
            <div className="mb-3 flex items-center gap-2">
              <span className="size-3 rounded-full bg-red-400" />
              <span className="size-3 rounded-full bg-yellow-400" />
              <span className="size-3 rounded-full bg-green-400" />
              <span className="ml-2 font-mono text-xs tracking-wide text-slate-400">
                terminal - {item.title}
              </span>
            </div>

            {isConnecting ? (
              <div className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-6 px-4 py-8">
                <Loader2 className="size-12 text-blue-400 animate-spin" />
                <div className="text-center space-y-2">
                  <h3 className="text-lg font-semibold text-slate-200">
                    Connecting...
                  </h3>
                  <p className="text-sm text-slate-400">
                    Establishing connection to terminal...
                  </p>
                </div>
              </div>
            ) : isConnected ? (
              <>
                <div
                  ref={outputRef}
                  className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] px-4 py-3 font-mono text-[15px] leading-[1.45] tracking-[0.01em]"
                >
                  {output.length === 0 ? (
                    <div className="text-lime-400">
                      [System] Terminal connected. Waiting for output...
                    </div>
                  ) : (
                    output.map((out, idx) => {
                      const text = out.stdout || ""
                      const isInput =
                        /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] #/.test(text)
                      return (
                        <span
                          key={idx}
                          className={`whitespace-pre ${isInput ? "text-green-400" : "text-blue-300"}`}
                        >
                          {text}
                        </span>
                      )
                    })
                  )}
                </div>

                <div className="mt-4 flex flex-col gap-3 lg:flex-row">
                  <Input
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Enter command and press enter to send"
                    className="h-10 border-zinc-700 bg-zinc-900/80 font-mono text-sm text-slate-100 placeholder:text-slate-500"
                  />
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      className="h-10 px-4 lg:min-w-24"
                      onClick={handleSendCommand}
                      disabled={!command.trim()}
                    >
                      <Send className="size-4" />
                      Send
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      className="h-10 px-4"
                      onClick={sendCtrlC}
                      title="Send Ctrl+C"
                    >
                      Ctrl+C
                    </Button>
                  </div>
                </div>
              </>
            ) : connectionError ? (
              <div className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-6 px-4 py-8">
                <div className="rounded-full bg-red-500/20 p-6">
                  <AlertCircle className="size-12 text-red-400" />
                </div>
                <div className="text-center space-y-2">
                  <h3 className="text-lg font-semibold text-slate-200">
                    Connection Error
                  </h3>
                  <p className="text-sm text-red-400 max-w-md">
                    {connectionError}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={reconnect}
                >
                  <Plug className="size-4 mr-2" />
                  Retry Connection
                </Button>
              </div>
            ) : (
              <div className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-6 px-4 py-8">
                <div className="rounded-full bg-muted/20 p-6">
                  <Plug className="size-12 text-muted-foreground" />
                </div>
                <div className="text-center space-y-2">
                  <h3 className="text-lg font-semibold text-slate-200">
                    Terminal Not Available
                  </h3>
                  <p className="text-sm text-slate-400 max-w-md">
                    {item.status !== "running"
                      ? "Start the item to connect to its terminal."
                      : "The daemon is offline. Please check the connection."}
                  </p>
                </div>
                <div className="grid gap-2 text-sm text-slate-400 bg-muted/10 rounded-lg p-4 w-full max-w-sm">
                  <div className="flex justify-between">
                    <span>Status:</span>
                    <span className="font-mono">{item.status}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Daemon:</span>
                    <span
                      className={`font-mono ${item.daemon_online ? "text-green-400" : "text-red-400"}`}
                    >
                      {item.daemon_online ? "Online" : "Offline"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Host:</span>
                    <span className="font-mono">
                      {item.socket_host || "localhost"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Port:</span>
                    <span className="font-mono">
                      {item.socket_port || 9000}
                    </span>
                  </div>
                </div>
                {item.status === "running" && !item.daemon_online && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={reconnect}
                  >
                    <Plug className="size-4 mr-2" />
                    Retry Connection
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <h2 className="text-xl font-semibold mb-4">Key Information</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <CopyValue label="ID" value={item.id} />
          <KeyValue label="Status" value={item.status} />
          <KeyValue label="Owner ID" value={item.owner_id} />
          <KeyValue label="Socket Host" value={item.socket_host} />
          <KeyValue label="Socket Port" value={item.socket_port?.toString()} />
          <KeyValue
            label="Socket Connected"
            value={item.socket_connected ? "Yes" : "No"}
          />
          <KeyValue label="Command" value={item.command} />
          <KeyValue label="Working Directory" value={item.working_directory} />
          <KeyValue
            label="Log Max Size (MB)"
            value={item.log_max_size_mb?.toString()}
          />
          <KeyValue label="Daemon URL" value={item.daemon_url} />
          <KeyValue label="Created At" value={formatDate(item.created_at)} />
          <KeyValue label="Updated At" value={formatDate(item.updated_at)} />
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Filter className="size-5 text-blue-500" />
            <h2 className="text-xl font-semibold">Input Filter Settings</h2>
          </div>
          <Button
            size="sm"
            onClick={handleSaveInputFilter}
            disabled={isSavingInputFilter}
          >
            {isSavingInputFilter ? (
              <Loader2 className="size-4 mr-2 animate-spin" />
            ) : (
              <Save className="size-4 mr-2" />
            )}
            Save
          </Button>
        </div>
        
        <div className="flex flex-wrap items-center gap-4 mb-4 p-3 rounded-lg border bg-muted/30">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Enabled</span>
            <button
              type="button"
              onClick={() => setInputFilterEnabled(!inputFilterEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                inputFilterEnabled ? 'bg-blue-500' : 'bg-muted'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  inputFilterEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
        
        <FilterRuleEditor
          value={inputFilterRules}
          onChange={setInputFilterRules}
          defaultRules={defaultInputRules as Record<string, FilterRule>}
        />
        
        <div className="mt-4 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Terminal className="size-4 text-blue-500" />
            <span className="text-sm font-medium">Test Input Filter</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Input Text</Label>
              <Textarea
                placeholder="Paste terminal output here to test..."
                className="font-mono text-xs h-40"
                value={inputTestText}
                onChange={(e) => setInputTestText(e.target.value)}
              />
              <Button
                size="sm"
                onClick={handleTestInputFilter}
                disabled={isTestingInputFilter}
                className="w-full"
              >
                {isTestingInputFilter ? (
                  <Loader2 className="size-4 mr-2 animate-spin" />
                ) : (
                  <Play className="size-4 mr-2" />
                )}
                Test Filter
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Filter Result</Label>
              <div className="rounded-md border bg-muted/30 p-3 h-40 overflow-auto">
                {inputTestResult ? (
                  <pre className="text-xs font-mono whitespace-pre-wrap">
                    {String(inputTestResult.result || "")}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">Click "Test Filter" to see results</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Shield className="size-5 text-orange-500" />
            <h2 className="text-xl font-semibold">Output Filter Settings</h2>
          </div>
          <Button
            size="sm"
            onClick={handleSaveOutputFilter}
            disabled={isSavingOutputFilter}
          >
            {isSavingOutputFilter ? (
              <Loader2 className="size-4 mr-2 animate-spin" />
            ) : (
              <Save className="size-4 mr-2" />
            )}
            Save
          </Button>
        </div>
        
        <div className="flex flex-wrap items-center gap-4 mb-4 p-3 rounded-lg border bg-muted/30">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Enabled</span>
            <button
              type="button"
              onClick={() => setOutputFilterEnabled(!outputFilterEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                outputFilterEnabled ? 'bg-orange-500' : 'bg-muted'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  outputFilterEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
        
        <FilterRuleEditor
          value={outputFilterRules}
          onChange={setOutputFilterRules}
          defaultRules={defaultOutputRules as Record<string, FilterRule>}
        />
        
        <div className="mt-4 rounded-lg border border-orange-500/30 bg-orange-500/5 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Shield className="size-4 text-orange-500" />
            <span className="text-sm font-medium">Test Output Filter</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Command to Test</Label>
              <Textarea
                placeholder="Enter a command to test filtering..."
                className="font-mono text-xs h-32"
                value={outputTestCommand}
                onChange={(e) => setOutputTestCommand(e.target.value)}
              />
              <Button
                size="sm"
                onClick={handleTestOutputFilter}
                disabled={isTestingOutputFilter}
                className="w-full"
              >
                {isTestingOutputFilter ? (
                  <Loader2 className="size-4 mr-2 animate-spin" />
                ) : (
                  <Play className="size-4 mr-2" />
                )}
                Test Command
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Filter Result</Label>
              <div className="rounded-md border bg-muted/30 p-3 h-32 overflow-auto">
                {outputTestResult ? (
                  <pre className="text-xs font-mono whitespace-pre-wrap">
                    {String(outputTestResult.result || "")}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">Click "Test Command" to see results</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <h2 className="text-xl font-semibold mb-4">Connected Users</h2>
        {item.connected_users &&
        Object.keys(item.connected_users).length > 0 ? (
          <div className="space-y-2">
            {Object.entries(item.connected_users).map(([sid, userInfo]) => (
              <div
                key={sid}
                className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <div className="size-2 rounded-full bg-green-500" />
                  <span className="font-mono text-sm">
                    {userInfo.user_uuid}
                  </span>
                </div>
                <span className="text-sm text-muted-foreground">
                  {userInfo.ip}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            <Users className="size-8 mx-auto mb-2 opacity-50" />
            <p>No connected users</p>
          </div>
        )}
      </section>
    </div>
  )
}

export const Route = createFileRoute("/_layout/items/$itemId")({
  component: ItemDetailRoute,
  head: () => ({
    meta: [
      {
        title: "Item Detail - TermMan",
      },
    ],
  }),
})

function ItemDetailRoute() {
  const { itemId } = Route.useParams()
  const queryClient = useQueryClient()

  const cachedDetailItem = queryClient.getQueryData<ItemWithExtras>([
    "items",
    "detail",
    itemId,
  ])
  const cachedItems = queryClient.getQueryData<ItemsResponse>(["items"])
  const cachedListItem = getCachedItem(cachedItems, itemId)
  const storedItem = useMemo(() => getStoredItemSnapshot(itemId), [itemId])
  const seedItem = useMemo(
    () =>
      createFallbackItem(
        itemId,
        cachedDetailItem ?? cachedListItem ?? storedItem,
      ),
    [cachedDetailItem, cachedListItem, itemId, storedItem],
  )

  const { data, error, isError, isFetching, isPending } = useQuery({
    ...getItemQueryOptions(itemId),
    initialData: cachedDetailItem ?? cachedListItem ?? storedItem,
  })

  useEffect(() => {
    if (data) {
      saveItemSnapshot(data as ItemWithExtras)
    }
  }, [data])

  const displayItem = (data as ItemWithExtras) ?? seedItem
  const message = isError
    ? getErrorMessage(error)
    : !data && (isPending || isFetching)
      ? "Loading live detail data..."
      : undefined

  return (
    <ItemDetailPage
      item={displayItem}
      isUsingFallback={!data || isError}
      message={message}
    />
  )
}
