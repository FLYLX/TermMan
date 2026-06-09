import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  Check,
  ChevronRight,
  Copy,
  Filter,
  Loader2,
  Play,
  Plug,
  Send,
  Shield,
  Terminal,
  Users,
  WifiOff,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  ApiError,
  type ItemPublic,
  ItemsService,
  type ItemUpdate,
} from "@/client"
import { ChatPanel } from "@/components/Items/ChatPanel"
import { FilterGeneratorCard } from "@/components/Items/FilterGeneratorCard"
import {
  type FilterRule,
  FilterRuleEditor,
} from "@/components/Items/FilterRuleEditor"
import { ItemFilesPanel } from "@/components/Items/ItemFilesPanel"
import ItemHandlersList from "@/components/Items/ItemHandlersList"
import {
  createFallbackItem,
  getStoredItemSnapshot,
  saveItemSnapshot,
} from "@/components/Items/itemDetailSnapshots"
import { useI18n } from "@/components/locale-provider"
import { MemoryManager } from "@/components/memory-manager"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { useTerminalConnection } from "@/hooks/useTerminalConnection"
import { getStatusLabel } from "@/lib/i18n"

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

type ItemDetailTab =
  | "terminal"
  | "files"
  | "handlers"
  | "filters"
  | "config"
  | "memory"

function createDefaultInputRules(): Record<string, FilterRule> {
  return {
    block_filter: {
      regex_patterns: ["violence|porn|gambling", "http://.*\\.exe"],
      action_type: "block",
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
      action_type: "ignore",
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
      action_type: "log",
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
          "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}": "***email***",
        },
      },
    },
  }
}

function createDefaultOutputRules(): Record<string, FilterRule> {
  return {
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
      action_type: "block",
    },
    ignore_filter: {
      regex_patterns: ["DEBUG\\s*:", "INFO\\s*:"],
      action_type: "ignore",
    },
    log_filter: {
      regex_patterns: ["sudo\\s+", "chmod\\s+", "chown\\s+"],
      action_type: "log",
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
          "-p\\s+\\S+": "-p ***",
        },
      },
    },
  }
}

function getInputFilterRules(item: ItemWithExtras): Record<string, FilterRule> {
  return item.input_filter_rules &&
    Object.keys(item.input_filter_rules).length > 0
    ? (item.input_filter_rules as Record<string, FilterRule>)
    : createDefaultInputRules()
}

function getOutputFilterRules(
  item: ItemWithExtras,
): Record<string, FilterRule> {
  return item.output_filter_rules &&
    Object.keys(item.output_filter_rules).length > 0
    ? (item.output_filter_rules as Record<string, FilterRule>)
    : createDefaultOutputRules()
}

function serializeFilterState(
  enabled: boolean,
  rules: Record<string, FilterRule>,
) {
  return JSON.stringify({
    enabled,
    rules,
  })
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

function formatDate(value: string | null | undefined, localeTag: string) {
  if (!value) {
    return null
  }

  return new Intl.DateTimeFormat(localeTag, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function getErrorMessage(error: Error | null, fallbackMessage: string) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: string })?.detail
    if (detail) {
      return detail
    }
  }

  return error?.message || fallbackMessage
}

function CopyValue({ label, value }: { label: string; value?: string | null }) {
  const [copiedText, copy] = useCopyToClipboard()
  const { t } = useI18n()
  const displayValue = value || t("common.notAvailable")
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
            <span className="sr-only">{t("common.copyLabel", { label })}</span>
          </Button>
        )}
      </div>
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  const { t } = useI18n()

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">
        {value || t("common.notAvailable")}
      </span>
    </div>
  )
}

function StatusBadge({
  status,
  className,
}: {
  status?: string
  className?: string
}) {
  const { locale } = useI18n()
  const label = getStatusLabel(locale, status)

  switch (status) {
    case "running":
      return (
        <Badge
          className={[
            "border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {label}
        </Badge>
      )
    case "starting":
      return (
        <Badge
          className={[
            "border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {label}
        </Badge>
      )
    case "stopping":
      return (
        <Badge
          className={[
            "border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {label}
        </Badge>
      )
    case "stopped":
      return (
        <Badge variant="secondary" className={className}>
          {label}
        </Badge>
      )
    case "error":
      return (
        <Badge
          className={[
            "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {label}
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className={className}>
          {label}
        </Badge>
      )
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
  const { t, locale, localeTag } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [command, setCommand] = useState("")
  const [activeTab, setActiveTab] = useState<ItemDetailTab>("terminal")
  const [visitedTabs, setVisitedTabs] = useState<Set<ItemDetailTab>>(
    () => new Set<ItemDetailTab>(["terminal"]),
  )
  const outputRef = useRef<HTMLDivElement>(null)
  const previousItemIdRef = useRef(item.id)
  const itemUpdatedAtRef = useRef(item.updated_at || "")
  const inputSyncedSignatureRef = useRef(
    serializeFilterState(
      item.input_filter_enabled || false,
      getInputFilterRules(item),
    ),
  )
  const outputSyncedSignatureRef = useRef(
    serializeFilterState(
      item.output_filter_enabled || false,
      getOutputFilterRules(item),
    ),
  )

  const [inputFilterEnabled, setInputFilterEnabled] = useState(
    item.input_filter_enabled || false,
  )
  const [inputFilterRules, setInputFilterRules] = useState<
    Record<string, FilterRule>
  >(getInputFilterRules(item))

  const [outputFilterEnabled, setOutputFilterEnabled] = useState(
    item.output_filter_enabled || false,
  )
  const [outputFilterRules, setOutputFilterRules] = useState<
    Record<string, FilterRule>
  >(getOutputFilterRules(item))
  const inputSignature = useMemo(
    () => serializeFilterState(inputFilterEnabled, inputFilterRules),
    [inputFilterEnabled, inputFilterRules],
  )
  const outputSignature = useMemo(
    () => serializeFilterState(outputFilterEnabled, outputFilterRules),
    [outputFilterEnabled, outputFilterRules],
  )
  const latestInputSignatureRef = useRef(inputSignature)
  const latestOutputSignatureRef = useRef(outputSignature)

  const [inputTestText, setInputTestText] = useState("")
  const [inputTestResult, setInputTestResult] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [isTestingInputFilter, setIsTestingInputFilter] = useState(false)

  const [outputTestCommand, setOutputTestCommand] = useState("")
  const [outputTestResult, setOutputTestResult] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [isTestingOutputFilter, setIsTestingOutputFilter] = useState(false)
  const [isEditingConfig, setIsEditingConfig] = useState(false)
  const [isSavingConfig, setIsSavingConfig] = useState(false)
  const [configForm, setConfigForm] = useState({
    title: item.title,
    description: item.description ?? "",
    socket_host: item.socket_host ?? "",
    socket_port: item.socket_port?.toString() ?? "",
    api_key: item.api_key ?? "",
    command: item.command ?? "",
    working_directory: item.working_directory ?? "",
    log_max_size_mb: item.log_max_size_mb?.toString() ?? "100",
  })
  const activateTab = (value: string) => {
    const nextTab = value as ItemDetailTab
    setActiveTab(nextTab)
    setVisitedTabs((current) => {
      if (current.has(nextTab)) {
        return current
      }
      const next = new Set(current)
      next.add(nextTab)
      return next
    })
  }
  const hasVisitedTab = (value: ItemDetailTab) => visitedTabs.has(value)

  useEffect(() => {
    setActiveTab("terminal")
    setVisitedTabs(new Set<ItemDetailTab>(["terminal"]))
  }, [item.id])

  useEffect(() => {
    const isNewItem = previousItemIdRef.current !== item.id
    const incomingUpdatedAt = item.updated_at || ""
    const isStaleItem =
      !isNewItem &&
      Boolean(itemUpdatedAtRef.current) &&
      Boolean(incomingUpdatedAt) &&
      incomingUpdatedAt < itemUpdatedAtRef.current

    if (isStaleItem) {
      return
    }

    const incomingInputEnabled = item.input_filter_enabled || false
    const incomingInputRules = getInputFilterRules(item)
    const incomingInputSignature = serializeFilterState(
      incomingInputEnabled,
      incomingInputRules,
    )
    const previousInputSignature = inputSyncedSignatureRef.current

    inputSyncedSignatureRef.current = incomingInputSignature
    if (
      isNewItem ||
      latestInputSignatureRef.current === previousInputSignature ||
      latestInputSignatureRef.current === incomingInputSignature
    ) {
      latestInputSignatureRef.current = incomingInputSignature
      setInputFilterEnabled(incomingInputEnabled)
      setInputFilterRules(incomingInputRules)
    }

    const incomingOutputEnabled = item.output_filter_enabled || false
    const incomingOutputRules = getOutputFilterRules(item)
    const incomingOutputSignature = serializeFilterState(
      incomingOutputEnabled,
      incomingOutputRules,
    )
    const previousOutputSignature = outputSyncedSignatureRef.current

    outputSyncedSignatureRef.current = incomingOutputSignature
    if (
      isNewItem ||
      latestOutputSignatureRef.current === previousOutputSignature ||
      latestOutputSignatureRef.current === incomingOutputSignature
    ) {
      latestOutputSignatureRef.current = incomingOutputSignature
      setOutputFilterEnabled(incomingOutputEnabled)
      setOutputFilterRules(incomingOutputRules)
    }

    previousItemIdRef.current = item.id
    itemUpdatedAtRef.current = incomingUpdatedAt
    if (isNewItem) {
      setConfigForm({
        title: item.title,
        description: item.description ?? "",
        socket_host: item.socket_host ?? "",
        socket_port: item.socket_port?.toString() ?? "",
        api_key: item.api_key ?? "",
        command: item.command ?? "",
        working_directory: item.working_directory ?? "",
        log_max_size_mb: item.log_max_size_mb?.toString() ?? "100",
      })
    }
  }, [item])

  useEffect(() => {
    latestInputSignatureRef.current = inputSignature
  }, [inputSignature])

  useEffect(() => {
    latestOutputSignatureRef.current = outputSignature
  }, [outputSignature])

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
      showSuccessToast(t("items.detail.terminalConnected"))
    },
    onDisconnected: () => {
      console.log("[Terminal] Disconnected")
    },
    onError: (error) => {
      console.error("[Terminal] Error:", error)
      showErrorToast(t("items.detail.terminalError", { error }))
    },
  })

  useEffect(() => {
    const timer = setTimeout(() => {
      if (outputRef.current) {
        outputRef.current.scrollTop = outputRef.current.scrollHeight
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [isConnected, output])

  const handleStartItem = async () => {
    try {
      const result = await ItemsService.startItem({ id: item.id })
      queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || t("items.detail.started"))
    } catch (error) {
      console.error("Failed to start item:", error)
      showErrorToast(t("items.detail.startFailed"))
    }
  }

  const handleStopItem = async () => {
    try {
      disconnect()
      const result = await ItemsService.stopItem({ id: item.id })
      queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || t("items.detail.stopped"))
    } catch (error) {
      console.error("Failed to stop item:", error)
      showErrorToast(t("items.detail.stopFailed"))
    }
  }

  const handleRestartItem = async () => {
    try {
      disconnect()
      const result = await ItemsService.restartItem({ id: item.id })
      await queryClient.invalidateQueries({ queryKey: ["item", item.id] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
      showSuccessToast(result.message || t("items.detail.restarted"))
      reconnect()
    } catch (error) {
      console.error("Failed to restart item:", error)
      showErrorToast(t("items.detail.restartFailed"))
    }
  }

  const handleSendCommand = () => {
    if (command.trim()) {
      sendCommand(command)
      setCommand("")
    }
  }

  const resetConfigForm = () => {
    setConfigForm({
      title: item.title,
      description: item.description ?? "",
      socket_host: item.socket_host ?? "",
      socket_port: item.socket_port?.toString() ?? "",
      api_key: item.api_key ?? "",
      command: item.command ?? "",
      working_directory: item.working_directory ?? "",
      log_max_size_mb: item.log_max_size_mb?.toString() ?? "100",
    })
  }

  const handleSaveConfig = async () => {
    const title = configForm.title.trim()
    if (!title) {
      showErrorToast("Title is required")
      return
    }

    const socketPort = configForm.socket_port.trim()
      ? Number(configForm.socket_port)
      : null
    const logMaxSize = configForm.log_max_size_mb.trim()
      ? Number(configForm.log_max_size_mb)
      : null

    setIsSavingConfig(true)
    try {
      const updatedItem = await ItemsService.updateItem({
        id: item.id,
        requestBody: {
          title,
          description: configForm.description.trim() || null,
          socket_host: configForm.socket_host.trim() || null,
          socket_port: socketPort,
          api_key: configForm.api_key.trim() || null,
          command: configForm.command.trim() || null,
          working_directory: configForm.working_directory.trim() || null,
          log_max_size_mb: logMaxSize,
        },
      })
      updateItemCaches(updatedItem)
      await queryClient.invalidateQueries({
        queryKey: ["items", "detail", item.id],
      })
      await queryClient.invalidateQueries({ queryKey: ["items"] })

      const daemonId =
        updatedItem.socket_host &&
        updatedItem.socket_port &&
        updatedItem.api_key
          ? `${updatedItem.socket_host}:${updatedItem.socket_port}:${updatedItem.api_key}`
          : null
      if (daemonId) {
        await ItemsService.reconnectDaemon({ daemonId }).catch(() => undefined)
      }

      showSuccessToast("Terminal configuration updated")
      setIsEditingConfig(false)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Failed to update terminal",
      )
    } finally {
      setIsSavingConfig(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendCommand()
    }
  }

  const updateItemCaches = (updatedItem: ItemPublic) => {
    const cachedItem = updatedItem as ItemWithExtras

    queryClient.setQueryData<ItemWithExtras>(
      ["items", "detail", updatedItem.id],
      (current) => ({ ...(current || {}), ...cachedItem }),
    )
    queryClient.setQueryData<ItemsResponse | undefined>(["items"], (current) =>
      current
        ? {
            ...current,
            data: current.data.map((entry) =>
              entry.id === updatedItem.id
                ? ({ ...entry, ...cachedItem } as ItemWithExtras)
                : entry,
            ),
          }
        : current,
    )
    saveItemSnapshot(cachedItem)
  }

  useEffect(() => {
    if (inputSignature === inputSyncedSignatureRef.current) {
      return
    }

    const timer = window.setTimeout(async () => {
      const payloadSignature = inputSignature
      const updateData: ItemUpdate = {
        input_filter_enabled: inputFilterEnabled,
        input_filter_rules: inputFilterRules,
      }

      try {
        const updatedItem = await ItemsService.updateItem({
          id: item.id,
          requestBody: updateData,
        })
        const savedSignature = serializeFilterState(
          updatedItem.input_filter_enabled || false,
          getInputFilterRules(updatedItem as ItemWithExtras),
        )

        inputSyncedSignatureRef.current = savedSignature
        itemUpdatedAtRef.current =
          updatedItem.updated_at || itemUpdatedAtRef.current

        if (latestInputSignatureRef.current === payloadSignature) {
          updateItemCaches(updatedItem)
        }
      } catch (error) {
        console.error("Failed to auto-save input filter:", error)
        showErrorToast(t("items.detail.inputFilterSaveFailed"))
      }
    }, 600)

    return () => window.clearTimeout(timer)
  }, [
    inputFilterEnabled,
    inputFilterRules,
    inputSignature,
    item.id,
    showErrorToast,
    t,
    updateItemCaches,
  ])

  useEffect(() => {
    if (outputSignature === outputSyncedSignatureRef.current) {
      return
    }

    const timer = window.setTimeout(async () => {
      const payloadSignature = outputSignature
      const updateData: ItemUpdate = {
        output_filter_enabled: outputFilterEnabled,
        output_filter_rules: outputFilterRules,
      }

      try {
        const updatedItem = await ItemsService.updateItem({
          id: item.id,
          requestBody: updateData,
        })
        const savedSignature = serializeFilterState(
          updatedItem.output_filter_enabled || false,
          getOutputFilterRules(updatedItem as ItemWithExtras),
        )

        outputSyncedSignatureRef.current = savedSignature
        itemUpdatedAtRef.current =
          updatedItem.updated_at || itemUpdatedAtRef.current

        if (latestOutputSignatureRef.current === payloadSignature) {
          updateItemCaches(updatedItem)
        }
      } catch (error) {
        console.error("Failed to auto-save output filter:", error)
        showErrorToast(t("items.detail.outputFilterSaveFailed"))
      }
    }, 600)

    return () => window.clearTimeout(timer)
  }, [
    item.id,
    outputFilterEnabled,
    outputFilterRules,
    outputSignature,
    showErrorToast,
    t,
    updateItemCaches,
  ])

  const handleTestInputFilter = async () => {
    if (!inputTestText.trim()) {
      showErrorToast(t("items.detail.enterTestText"))
      return
    }
    setIsTestingInputFilter(true)
    try {
      const result = await ItemsService.testInputFilter({
        id: item.id,
        requestBody: { test_text: inputTestText },
      })
      setInputTestResult(result)
    } catch (error) {
      console.error("Failed to test input filter:", error)
      showErrorToast(t("items.detail.inputFilterTestFailed"))
    } finally {
      setIsTestingInputFilter(false)
    }
  }

  const handleTestOutputFilter = async () => {
    if (!outputTestCommand.trim()) {
      showErrorToast(t("items.detail.enterTestCommand"))
      return
    }
    setIsTestingOutputFilter(true)
    try {
      const result = await ItemsService.testOutputFilter({
        id: item.id,
        requestBody: { command: outputTestCommand },
      })
      setOutputTestResult(result)
    } catch (error) {
      console.error("Failed to test output filter:", error)
      showErrorToast(t("items.detail.outputFilterTestFailed"))
    } finally {
      setIsTestingOutputFilter(false)
    }
  }

  return (
    <div className="flex gap-4 w-full">
      <div className="flex-1 min-w-0">
        <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-2.5">
          <section className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Link to="/items" className="hover:text-foreground">
                {t("items.pageTitle")}
              </Link>
              <ChevronRight className="size-3.5" />
              <span className="text-foreground">{item.title}</span>
            </div>

            <div className="rounded-xl border bg-card/90 px-3 py-2 shadow-sm">
              <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="break-words text-base font-semibold leading-tight tracking-tight sm:text-lg">
                      {item.title}
                    </h1>
                    <StatusBadge
                      status={item.status}
                      className="h-5 px-1.5 text-[10px]"
                    />
                    <Badge
                      variant="outline"
                      className={`h-5 px-1.5 text-[10px] ${
                        item.daemon_online
                          ? "border-green-500/30 text-green-600 dark:text-green-400"
                          : "border-red-500/30 text-red-600 dark:text-red-400"
                      }`}
                    >
                      {item.daemon_online
                        ? t("items.detail.daemonOnline")
                        : t("items.detail.daemonOffline")}
                    </Badge>
                    {isUsingFallback && (
                      <Badge
                        variant="secondary"
                        className="h-5 px-1.5 text-[10px]"
                      >
                        {t("items.detail.fallbackMode")}
                      </Badge>
                    )}
                  </div>

                  <p className="max-w-3xl text-[11px] leading-4 text-muted-foreground sm:text-xs">
                    {item.description || t("items.detail.noDescriptionYet")}
                  </p>
                </div>

                <div className="flex shrink-0 flex-wrap gap-2 xl:w-auto xl:justify-end">
                  <Button
                    type="button"
                    size="sm"
                    className="h-8 min-w-20 px-3.5 text-xs"
                    onClick={handleStartItem}
                  >
                    {t("items.detail.start")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 min-w-20 px-3.5 text-xs"
                    onClick={handleStopItem}
                  >
                    {t("items.detail.stop")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 min-w-20 px-3.5 text-xs"
                    onClick={handleRestartItem}
                  >
                    {t("items.detail.restart")}
                  </Button>
                </div>
              </div>

              {isUsingFallback && (
                <div className="mt-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm">
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

          <Tabs
            value={activeTab}
            onValueChange={activateTab}
            className="gap-2.5"
          >
            <div className="overflow-x-auto">
              <TabsList className="h-auto min-w-max gap-1 bg-muted/70 p-1">
                <TabsTrigger value="terminal">
                  {t("items.detail.terminal")}
                </TabsTrigger>
                <TabsTrigger value="files">
                  {t("items.detail.files")}
                </TabsTrigger>
                <TabsTrigger value="handlers">
                  {t("items.detail.handlers")}
                </TabsTrigger>
                <TabsTrigger value="filters">
                  {t("items.detail.filters")}
                </TabsTrigger>
                <TabsTrigger value="config">
                  {t("items.detail.config")}
                </TabsTrigger>
                <TabsTrigger value="memory">
                  {t("items.detail.memory")}
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="terminal">
              <section className="rounded-2xl border bg-card/85 p-2.5 shadow-sm">
                <div className="flex flex-col gap-4 xl:flex-row">
                  <div className="flex-1 min-w-0">
                    <div className="space-y-2.5">
                      <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <h2 className="text-base font-semibold">
                            {t("items.detail.terminalTitle")}
                          </h2>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {isConnecting ? (
                            <Badge
                              variant="outline"
                              className="border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                            >
                              <Loader2 className="size-3 mr-1 animate-spin" />
                              {t("items.detail.connecting")}
                            </Badge>
                          ) : isConnected ? (
                            <>
                              <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
                                {t("common.connected")}
                              </Badge>
                              <Badge variant="secondary">
                                {t("items.detail.realtimeConsole")}
                              </Badge>
                            </>
                          ) : connectionError ? (
                            <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
                              <AlertCircle className="size-3 mr-1" />
                              {t("common.error")}
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
                            >
                              <WifiOff className="size-3 mr-1" />
                              {t("common.disconnected")}
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
                            {t("items.detail.terminal")} - {item.title}
                          </span>
                        </div>

                        {isConnecting ? (
                          <div className="h-[34rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-4 px-4 py-8">
                            <Loader2 className="size-8 text-blue-400 animate-spin" />
                            <div className="text-center space-y-1">
                              <h3 className="text-base font-semibold text-slate-200">
                                {t("items.detail.connecting")}
                              </h3>
                              <p className="text-xs text-slate-400">
                                {t("items.detail.establishingConnection")}
                              </p>
                            </div>
                          </div>
                        ) : isConnected ? (
                          <>
                            <div
                              ref={outputRef}
                              className="h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] px-4 py-3 font-mono text-[15px] leading-[1.45] tracking-[0.01em]"
                            >
                              {output.length === 0 ? (
                                <div className="text-lime-400">
                                  {t("items.detail.terminalConnectedWaiting")}
                                </div>
                              ) : (
                                output.map((out, idx) => {
                                  const text = out.stdout || ""
                                  const isInput =
                                    /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] #/.test(
                                      text,
                                    )
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
                                placeholder={t("items.detail.enterCommand")}
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
                                  {t("items.detail.send")}
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="destructive"
                                  className="h-10 px-4"
                                  onClick={sendCtrlC}
                                  title={t("items.detail.sendCtrlC")}
                                >
                                  Ctrl+C
                                </Button>
                              </div>
                            </div>
                          </>
                        ) : connectionError ? (
                          <div className="h-[34rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-4 px-4 py-8">
                            <div className="rounded-full bg-red-500/20 p-4">
                              <AlertCircle className="size-8 text-red-400" />
                            </div>
                            <div className="text-center space-y-1">
                              <h3 className="text-base font-semibold text-slate-200">
                                {t("items.detail.connectionErrorTitle")}
                              </h3>
                              <p className="text-xs text-red-400 max-w-md">
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
                              {t("items.detail.retryConnection")}
                            </Button>
                          </div>
                        ) : (
                          <div className="h-[34rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-4 px-4 py-8">
                            <div className="rounded-full bg-muted/20 p-4">
                              <Plug className="size-8 text-muted-foreground" />
                            </div>
                            <div className="text-center space-y-1">
                              <h3 className="text-base font-semibold text-slate-200">
                                {t("items.detail.terminalNotAvailable")}
                              </h3>
                              <p className="text-xs text-slate-400 max-w-md">
                                {item.status !== "running"
                                  ? t("items.detail.startItemToConnect")
                                  : t("items.detail.daemonOfflineHint")}
                              </p>
                            </div>
                            <div className="grid gap-2 text-xs text-slate-400 bg-muted/10 rounded-lg p-3 w-full max-w-sm">
                              <div className="flex justify-between">
                                <span>{t("common.status")}:</span>
                                <span className="font-mono">
                                  {getStatusLabel(locale, item.status)}
                                </span>
                              </div>
                              <div className="flex justify-between">
                                <span>{t("items.detail.daemonLabel")}</span>
                                <span
                                  className={`font-mono ${item.daemon_online ? "text-green-400" : "text-red-400"}`}
                                >
                                  {item.daemon_online
                                    ? t("common.online")
                                    : t("common.offline")}
                                </span>
                              </div>
                              <div className="flex justify-between">
                                <span>{t("items.detail.hostLabel")}</span>
                                <span className="font-mono">
                                  {item.socket_host ||
                                    t("items.detail.localhost")}
                                </span>
                              </div>
                              <div className="flex justify-between">
                                <span>{t("items.detail.portLabel")}</span>
                                <span className="font-mono">
                                  {item.socket_port || 9000}
                                </span>
                              </div>
                            </div>
                            {item.status === "running" &&
                              !item.daemon_online && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="mt-2"
                                  onClick={reconnect}
                                >
                                  <Plug className="size-4 mr-2" />
                                  {t("items.detail.retryConnection")}
                                </Button>
                              )}
                          </div>
                        )}
                      </div>

                      <div className="grid gap-2 rounded-xl border border-border/50 bg-muted/10 px-3 py-2 text-[11px] text-muted-foreground sm:grid-cols-2 sm:gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <div className="shrink-0 uppercase tracking-[0.14em]">
                            {t("items.workingDirectory")}
                          </div>
                          <div className="truncate font-mono text-foreground/90">
                            {item.working_directory || t("common.notSet")}
                          </div>
                        </div>
                        <div className="flex min-w-0 items-center gap-2">
                          <div className="shrink-0 uppercase tracking-[0.14em]">
                            {t("items.detail.startupCommand")}
                          </div>
                          <div className="truncate font-mono text-foreground/90">
                            {item.command || t("common.notSet")}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="w-full shrink-0 xl:w-[23rem]">
                    <div className="rounded-2xl border bg-card/85 shadow-sm h-[42rem] overflow-hidden">
                      <ChatPanel itemId={item.id} />
                    </div>
                  </div>
                </div>
              </section>
            </TabsContent>

            <TabsContent value="files">
              {hasVisitedTab("files") ? (
                <ItemFilesPanel itemId={item.id} />
              ) : null}
            </TabsContent>

            <TabsContent value="handlers">
              {hasVisitedTab("handlers") ? (
                <ItemHandlersList itemId={item.id} />
              ) : null}
            </TabsContent>

            <TabsContent value="filters" className="space-y-4">
              {hasVisitedTab("filters") ? (
                <>
                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex items-start gap-2">
                        <Filter className="mt-1 size-5 text-blue-500" />
                        <div>
                          <h2 className="text-xl font-semibold">
                            {t("items.detail.inputFilterSettings")}
                          </h2>
                          <p className="text-xs text-muted-foreground">
                            {t("items.detail.inputFilterFlowDescription")}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center justify-end gap-x-4 gap-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {t("common.enabled")}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              setInputFilterEnabled(!inputFilterEnabled)
                            }
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                              inputFilterEnabled ? "bg-blue-500" : "bg-muted"
                            }`}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                inputFilterEnabled
                                  ? "translate-x-6"
                                  : "translate-x-1"
                              }`}
                            />
                          </button>
                        </div>
                      </div>
                    </div>

                    <FilterGeneratorCard
                      itemId={item.id}
                      target="input"
                      currentRules={inputFilterRules}
                      onApply={setInputFilterRules}
                    />

                    <FilterRuleEditor
                      value={inputFilterRules}
                      onChange={setInputFilterRules}
                      defaultRules={createDefaultInputRules()}
                    />

                    <div className="mt-4 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <Terminal className="size-4 text-blue-500" />
                        <span className="text-sm font-medium">
                          {t("items.detail.testInputFilter")}
                        </span>
                      </div>
                      <div className="grid gap-4 lg:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">
                            {t("items.detail.inputText")}
                          </Label>
                          <Textarea
                            placeholder={t("items.detail.pasteTerminalOutput")}
                            className="h-40 font-mono text-xs"
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
                              <Loader2 className="mr-2 size-4 animate-spin" />
                            ) : (
                              <Play className="mr-2 size-4" />
                            )}
                            {t("items.detail.testFilter")}
                          </Button>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">
                            {t("items.detail.filterResult")}
                          </Label>
                          <div className="h-40 overflow-auto rounded-md border bg-muted/30 p-3">
                            {inputTestResult ? (
                              <pre className="whitespace-pre-wrap text-xs font-mono">
                                {String(inputTestResult.result || "")}
                              </pre>
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                {t("items.detail.clickTestFilter")}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex items-start gap-2">
                        <Shield className="mt-1 size-5 text-orange-500" />
                        <div>
                          <h2 className="text-xl font-semibold">
                            {t("items.detail.outputFilterSettings")}
                          </h2>
                          <p className="text-xs text-muted-foreground">
                            {t("items.detail.outputFilterFlowDescription")}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center justify-end gap-x-4 gap-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {t("common.enabled")}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              setOutputFilterEnabled(!outputFilterEnabled)
                            }
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                              outputFilterEnabled ? "bg-orange-500" : "bg-muted"
                            }`}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                outputFilterEnabled
                                  ? "translate-x-6"
                                  : "translate-x-1"
                              }`}
                            />
                          </button>
                        </div>
                      </div>
                    </div>

                    <FilterGeneratorCard
                      itemId={item.id}
                      target="output"
                      currentRules={outputFilterRules}
                      onApply={setOutputFilterRules}
                    />

                    <FilterRuleEditor
                      value={outputFilterRules}
                      onChange={setOutputFilterRules}
                      defaultRules={createDefaultOutputRules()}
                    />

                    <div className="mt-4 rounded-lg border border-orange-500/30 bg-orange-500/5 p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <Shield className="size-4 text-orange-500" />
                        <span className="text-sm font-medium">
                          {t("items.detail.testOutputFilter")}
                        </span>
                      </div>
                      <div className="grid gap-4 lg:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">
                            {t("items.detail.commandToTest")}
                          </Label>
                          <Textarea
                            placeholder={t("items.detail.enterCommandToTest")}
                            className="h-32 font-mono text-xs"
                            value={outputTestCommand}
                            onChange={(e) =>
                              setOutputTestCommand(e.target.value)
                            }
                          />
                          <Button
                            size="sm"
                            onClick={handleTestOutputFilter}
                            disabled={isTestingOutputFilter}
                            className="w-full"
                          >
                            {isTestingOutputFilter ? (
                              <Loader2 className="mr-2 size-4 animate-spin" />
                            ) : (
                              <Play className="mr-2 size-4" />
                            )}
                            {t("items.detail.testCommand")}
                          </Button>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">
                            {t("items.detail.filterResult")}
                          </Label>
                          <div className="h-32 overflow-auto rounded-md border bg-muted/30 p-3">
                            {outputTestResult ? (
                              <pre className="whitespace-pre-wrap text-xs font-mono">
                                {String(outputTestResult.result || "")}
                              </pre>
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                {t("items.detail.clickTestCommand")}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>
                </>
              ) : null}
            </TabsContent>

            <TabsContent value="config" className="space-y-4">
              {hasVisitedTab("config") ? (
                <>
                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <h2 className="text-xl font-semibold">
                        {t("items.detail.keyInformation")}
                      </h2>
                      <div className="flex gap-2">
                        {isEditingConfig ? (
                          <>
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => {
                                resetConfigForm()
                                setIsEditingConfig(false)
                              }}
                              disabled={isSavingConfig}
                            >
                              {t("common.cancel")}
                            </Button>
                            <Button
                              type="button"
                              onClick={() => void handleSaveConfig()}
                              disabled={isSavingConfig}
                            >
                              {isSavingConfig ? (
                                <Loader2 className="mr-2 size-4 animate-spin" />
                              ) : null}
                              {t("common.save")}
                            </Button>
                          </>
                        ) : (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => setIsEditingConfig(true)}
                          >
                            Edit
                          </Button>
                        )}
                      </div>
                    </div>
                    {isEditingConfig ? (
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="grid gap-2">
                          <Label>Title</Label>
                          <Input
                            value={configForm.title}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                title: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>Description</Label>
                          <Input
                            value={configForm.description}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                description: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>{t("items.detail.socketHost")}</Label>
                          <Input
                            value={configForm.socket_host}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                socket_host: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>{t("items.detail.socketPort")}</Label>
                          <Input
                            type="number"
                            value={configForm.socket_port}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                socket_port: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>Daemon API Key</Label>
                          <Input
                            type="password"
                            value={configForm.api_key}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                api_key: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>{t("items.detail.logMaxSize")}</Label>
                          <Input
                            type="number"
                            value={configForm.log_max_size_mb}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                log_max_size_mb: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>{t("items.detail.command")}</Label>
                          <Input
                            value={configForm.command}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                command: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label>{t("items.workingDirectory")}</Label>
                          <Input
                            value={configForm.working_directory}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                working_directory: event.target.value,
                              }))
                            }
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        <CopyValue label={t("common.id")} value={item.id} />
                        <KeyValue
                          label={t("common.status")}
                          value={getStatusLabel(locale, item.status)}
                        />
                        <KeyValue
                          label={t("common.ownerId")}
                          value={item.owner_id}
                        />
                        <KeyValue
                          label={t("items.detail.socketHost")}
                          value={item.socket_host}
                        />
                        <KeyValue
                          label={t("items.detail.socketPort")}
                          value={item.socket_port?.toString()}
                        />
                        <KeyValue
                          label={t("items.detail.socketConnected")}
                          value={
                            item.socket_connected
                              ? t("common.yes")
                              : t("common.no")
                          }
                        />
                        <KeyValue
                          label={t("items.detail.command")}
                          value={item.command}
                        />
                        <KeyValue
                          label={t("items.workingDirectory")}
                          value={item.working_directory}
                        />
                        <KeyValue
                          label={t("items.detail.logMaxSize")}
                          value={item.log_max_size_mb?.toString()}
                        />
                        <KeyValue
                          label={t("items.detail.daemonUrl")}
                          value={item.daemon_url}
                        />
                        <KeyValue
                          label={t("common.createdAt")}
                          value={
                            formatDate(item.created_at, localeTag) || undefined
                          }
                        />
                        <KeyValue
                          label={t("common.updatedAt")}
                          value={
                            formatDate(item.updated_at, localeTag) || undefined
                          }
                        />
                      </div>
                    )}
                  </section>

                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <h2 className="mb-4 text-xl font-semibold">
                      {t("items.detail.connectedUsers")}
                    </h2>
                    {item.connected_users &&
                    Object.keys(item.connected_users).length > 0 ? (
                      <div className="space-y-2">
                        {Object.entries(item.connected_users).map(
                          ([sid, userInfo]) => (
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
                          ),
                        )}
                      </div>
                    ) : (
                      <div className="py-8 text-center text-muted-foreground">
                        <Users className="mx-auto mb-2 size-8 opacity-50" />
                        <p>{t("items.detail.noConnectedUsers")}</p>
                      </div>
                    )}
                  </section>
                </>
              ) : null}
            </TabsContent>

            <TabsContent value="memory">
              {hasVisitedTab("memory") ? (
                <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                  <MemoryManager itemId={item.id} />
                </section>
              ) : null}
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}

export const Route = createFileRoute("/_layout/items/$itemId")({
  component: ItemDetailRoute,
  head: () => ({
    meta: [
      {
        title: "Terminal Detail - TermMan",
      },
    ],
  }),
})

function ItemDetailRoute() {
  const { itemId } = Route.useParams()
  const queryClient = useQueryClient()
  const { t } = useI18n()

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
    ? getErrorMessage(error, t("items.detail.unableToLoad"))
    : !data && (isPending || isFetching)
      ? t("items.detail.loadingLiveData")
      : undefined

  return (
    <ItemDetailPage
      item={displayItem}
      isUsingFallback={!data || isError}
      message={message}
    />
  )
}
