import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  Bot,
  Check,
  ChevronRight,
  Copy,
  Filter,
  Loader2,
  MessageSquare,
  Moon,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Send,
  Server,
  Shield,
  Square,
  Terminal,
  Trash2,
  Users,
  WifiOff,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ApiError,
  type ItemPublic,
  ItemsService,
  type ItemUpdate,
} from "@/client"
import { OpenAPI } from "@/client/core/OpenAPI"
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
import { ScheduledTasksManager } from "@/components/scheduled-tasks-manager"
import {
  getItemRobotControllerStatus,
  getItemRobotControllerStatusQueryKey,
  type ItemRobotControllerStatusRecord,
  type ItemRobotControllerStatusResponse,
  type RobotConversationControllerStatus,
} from "@/components/Robots/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PasswordInput } from "@/components/ui/password-input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import {
  type TerminalOutput,
  useTerminalConnection,
} from "@/hooks/useTerminalConnection"
import { getStatusLabel } from "@/lib/i18n"
import { getPluginsQueryOptions, isPluginEnabled } from "@/lib/plugins-api"

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
  | "websocket"
  | "qq-debug"
  | "files"
  | "handlers"
  | "filters"
  | "config"
  | "memory"
  | "scheduled-tasks"

type TerminalWebSocketServerStatus = {
  server_id: string
  item_id: string
  name: string
  host: string
  port: number
  token: string
  heartbeat_interval: number
  message_format: "json"
  running: boolean
  client_count: number
  url: string
}

type TerminalWebSocketServerListResponse = {
  servers: TerminalWebSocketServerStatus[]
}

type BackgroundJob = {
  job_id: string
  item_uuid?: string
  command: string
  pid?: number
  started_at?: string
  elapsed_seconds?: number
  cancel_requested?: boolean
}

type BackgroundJobsResponse = {
  success: boolean
  jobs: BackgroundJob[]
  count: number
  daemon_online?: boolean
  error?: string | null
}

type TerminalOutputGroup =
  | {
      kind: "terminal"
      entries: TerminalOutput[]
    }
  | {
      kind: "job"
      entries: TerminalOutput[]
      jobId: string
    }

type TerminalWebSocketServerForm = {
  name: string
  host: string
  port: string
  token: string
  heartbeat_interval: string
  message_format: "json"
}

function createTerminalWsForm(itemTitle: string): TerminalWebSocketServerForm {
  return {
    name: `${itemTitle} WS`,
    host: "0.0.0.0",
    port: "",
    token: "",
    heartbeat_interval: "30",
    message_format: "json",
  }
}

function getTerminalWsConnectionUrl(
  server: TerminalWebSocketServerStatus,
): string {
  const host =
    server.host === "0.0.0.0" || server.host === "::"
      ? getTerminalWsPublicHost()
      : server.host
  return `ws://${host}:${server.port}/?token=${encodeURIComponent(server.token)}`
}

function getTerminalWsPublicHost(): string {
  try {
    const apiUrl = new URL(
      OpenAPI.BASE || window.location.origin,
      window.location.origin,
    )
    if (apiUrl.hostname) {
      return apiUrl.hostname
    }
  } catch {
    // Fall through to the browser location below.
  }
  return window.location.hostname || "127.0.0.1"
}

async function requestTerminalWebSocket<T>(
  itemId: string,
  path = "",
  init: RequestInit = {},
): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/items/${itemId}/websocket-servers${path}`,
    {
      ...init,
      headers,
    },
  )
  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => undefined)
    : await response.text().catch(() => "")

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : String(payload || `HTTP ${response.status}`)
    throw new Error(detail)
  }

  return payload as T
}

async function requestItemJobs<T>(
  itemId: string,
  path = "",
  init: RequestInit = {},
): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/items/${itemId}/jobs${path}`,
    {
      ...init,
      headers,
    },
  )
  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => undefined)
    : await response.text().catch(() => "")

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : String(payload || `HTTP ${response.status}`)
    throw new Error(detail)
  }

  return payload as T
}

function formatJobElapsed(seconds: number | undefined): string {
  const total = Math.max(0, Math.floor(Number(seconds || 0)))
  if (total < 60) {
    return `${total}s`
  }
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes < 60) {
    return `${minutes}m ${rest}s`
  }
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

function shortenJobCommand(command: string): string {
  const normalized = command.replace(/\s+/g, " ").trim()
  if (normalized.length <= 120) {
    return normalized || "(empty command)"
  }
  return `${normalized.slice(0, 117)}...`
}

function getTerminalOutputText(entry: TerminalOutput): string {
  return entry.stdout || entry.stderr || entry.stdin || ""
}

function isTerminalInput(entry: TerminalOutput, text: string): boolean {
  return (
    Boolean(entry.stdin) ||
    /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] #/.test(text)
  )
}

function isBackgroundJobOutput(entry: TerminalOutput): boolean {
  return entry.source === "job" || Boolean(entry.job_id)
}

function buildTerminalOutputGroups(
  output: TerminalOutput[],
): TerminalOutputGroup[] {
  const groups: TerminalOutputGroup[] = []

  for (const entry of output) {
    if (isBackgroundJobOutput(entry)) {
      const jobId = entry.job_id || "job"
      const lastGroup = groups[groups.length - 1]
      if (lastGroup?.kind === "job" && lastGroup.jobId === jobId) {
        lastGroup.entries.push(entry)
      } else {
        groups.push({ kind: "job", entries: [entry], jobId })
      }
      continue
    }

    const lastGroup = groups[groups.length - 1]
    if (lastGroup?.kind === "terminal") {
      lastGroup.entries.push(entry)
    } else {
      groups.push({ kind: "terminal", entries: [entry] })
    }
  }

  return groups
}

function getTerminalJobStatusLabel(entry: TerminalOutput | undefined): string {
  if (!entry) {
    return "Job"
  }
  if (entry.cancelled) {
    return "已取消"
  }
  if (entry.timed_out) {
    return "超时"
  }
  if (typeof entry.exit_code === "number") {
    return entry.exit_code === 0 ? "完成" : `失败 ${entry.exit_code}`
  }
  if (entry.status === "running") {
    return "运行中"
  }
  if (entry.status === "finished") {
    return "完成"
  }
  return entry.status || "Job"
}

function getTerminalJobTone(entry: TerminalOutput | undefined): {
  border: string
  header: string
  badge: string
  text: string
} {
  if (entry?.cancelled || entry?.timed_out) {
    return {
      border: "border-amber-500/35 bg-amber-500/10",
      header: "border-amber-500/20 bg-amber-500/10",
      badge: "border-amber-500/30 bg-amber-500/15 text-amber-200",
      text: "text-amber-100",
    }
  }
  if (typeof entry?.exit_code === "number" && entry.exit_code !== 0) {
    return {
      border: "border-red-500/35 bg-red-500/10",
      header: "border-red-500/20 bg-red-500/10",
      badge: "border-red-500/30 bg-red-500/15 text-red-200",
      text: "text-red-100",
    }
  }
  if (entry?.status === "finished") {
    return {
      border: "border-emerald-500/30 bg-emerald-500/10",
      header: "border-emerald-500/20 bg-emerald-500/10",
      badge: "border-emerald-500/30 bg-emerald-500/15 text-emerald-200",
      text: "text-emerald-100",
    }
  }
  return {
    border: "border-cyan-500/30 bg-cyan-500/10",
    header: "border-cyan-500/20 bg-cyan-500/10",
    badge: "border-cyan-500/30 bg-cyan-500/15 text-cyan-200",
    text: "text-cyan-100",
  }
}

function TerminalJobOutputBlock({
  group,
}: {
  group: Extract<TerminalOutputGroup, { kind: "job" }>
}) {
  const latestEntry = group.entries[group.entries.length - 1]
  const tone = getTerminalJobTone(latestEntry)
  const text = group.entries.map(getTerminalOutputText).join("")

  return (
    <div className={`my-2 overflow-hidden rounded-lg border ${tone.border}`}>
      <div
        className={`flex min-h-8 flex-wrap items-center gap-2 border-b px-3 py-1.5 ${tone.header}`}
      >
        <Server className="size-3.5 shrink-0 text-cyan-300" />
        <span className="font-sans text-[11px] font-semibold text-slate-100">
          后台 Job 输出
        </span>
        <span className="rounded-full border border-zinc-700 bg-zinc-950/70 px-2 py-0.5 text-[10px] text-slate-300">
          {group.jobId}
        </span>
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] ${tone.badge}`}
        >
          {getTerminalJobStatusLabel(latestEntry)}
        </span>
      </div>
      <pre
        className={`whitespace-pre-wrap px-3 py-2 text-[12px] leading-5 ${tone.text}`}
      >
        {text}
      </pre>
    </div>
  )
}

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

const COMMON_INPUT_NOISE_RULES: Array<{
  key: string
  label: string
  description: string
  rule: FilterRule
}> = [
  {
    key: "noise_ftb_backups",
    label: "FTBBackups 自动备份",
    description: "拦截普通自动备份状态，不影响错误和玩家聊天。",
    rule: {
      regex_patterns: [
        "\\[.*FTBBackups/\\]:\\s*(Attempting to create an automatic backup|Starting automatic backup|Created backup|Backup .* completed|Skipping automatic backup)",
      ],
      action_type: "block",
      reason: "Repeated FTBBackups automatic backup status line.",
    },
  },
]

function mergeFilterRule(
  rules: Record<string, FilterRule>,
  key: string,
  rule: FilterRule,
): Record<string, FilterRule> {
  const current = rules[key]
  if (!current) {
    return {
      ...rules,
      [key]: rule,
    }
  }

  const mergedPatterns = Array.from(
    new Set([...(current.regex_patterns || []), ...rule.regex_patterns]),
  )
  return {
    ...rules,
    [key]: {
      ...current,
      ...rule,
      regex_patterns: mergedPatterns,
      reason: current.reason || rule.reason,
    },
  }
}

function hasFilterRule(
  rules: Record<string, FilterRule>,
  key: string,
  rule: FilterRule,
) {
  const current = rules[key]
  if (!current) {
    return false
  }
  return rule.regex_patterns.every((pattern) =>
    current.regex_patterns.includes(pattern),
  )
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

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
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

type RobotControllerRow = {
  robot: ItemRobotControllerStatusRecord
  controller: RobotConversationControllerStatus
}

type RobotPendingReplyRow = RobotControllerRow & {
  message: NonNullable<
    RobotConversationControllerStatus["pending_messages"]
  >[number]
}

function getRobotControllerRows(
  data: ItemRobotControllerStatusResponse | undefined,
): RobotControllerRow[] {
  if (!data) {
    return []
  }

  return data.robots
    .filter((robot) => robot.is_enabled && robot.allow_chat)
    .flatMap((robot) =>
      robot.conversation_controllers.map((controller) => ({
        robot,
        controller,
      })),
    )
    .sort(
      (left, right) =>
        Date.parse(right.controller.updated_at || "") -
        Date.parse(left.controller.updated_at || ""),
    )
}

function getRobotPendingReplyRows(
  data: ItemRobotControllerStatusResponse | undefined,
): RobotPendingReplyRow[] {
  return getRobotControllerRows(data)
    .flatMap(({ robot, controller }) =>
      (controller.pending_messages || []).map((message) => ({
        robot,
        controller,
        message,
      })),
    )
    .sort(
      (left, right) =>
        Date.parse(left.message.enqueued_at || "") -
        Date.parse(right.message.enqueued_at || ""),
    )
}

function getRobotPendingReplyCount(
  data: ItemRobotControllerStatusResponse | undefined,
) {
  return getRobotPendingReplyRows(data).length
}

function getEnabledRobotCount(
  data: ItemRobotControllerStatusResponse | undefined,
) {
  return (data?.robots || []).filter(
    (robot) => robot.is_enabled && robot.allow_chat,
  ).length
}

function getRobotControllerSecondsRemaining(
  controller: RobotConversationControllerStatus | undefined,
  snapshotAtMs = 0,
  nowMs = Date.now(),
) {
  const reportedSeconds = Number(controller?.seconds_remaining)
  if (Number.isFinite(reportedSeconds)) {
    const elapsedSeconds =
      snapshotAtMs > 0 ? Math.max(0, (nowMs - snapshotAtMs) / 1000) : 0
    return Math.max(0, Math.ceil(reportedSeconds - elapsedSeconds))
  }

  if (controller?.expires_at) {
    const expiresAt = Date.parse(controller.expires_at)
    if (Number.isFinite(expiresAt)) {
      return Math.max(0, Math.ceil((expiresAt - nowMs) / 1000))
    }
  }
  return 0
}

function isRobotControllerProcessing(
  controller: RobotConversationControllerStatus | undefined,
) {
  return controller?.status === "processing" || Boolean(controller?.processing)
}

function isRobotControllerAwake(
  controller: RobotConversationControllerStatus | undefined,
  snapshotAtMs = 0,
  nowMs = Date.now(),
) {
  return Boolean(
    controller?.awake &&
      getRobotControllerSecondsRemaining(controller, snapshotAtMs, nowMs) > 0,
  )
}

function hasActiveRobotController(
  data: ItemRobotControllerStatusResponse | undefined,
) {
  return getRobotControllerRows(data).some(
    ({ controller }) =>
      isRobotControllerProcessing(controller) ||
      isRobotControllerAwake(controller),
  )
}

function getLatestRobotControllerRow(
  data: ItemRobotControllerStatusResponse | undefined,
  snapshotAtMs = 0,
  nowMs = Date.now(),
) {
  const rows = getRobotControllerRows(data)
  return (
    rows.find((row) => isRobotControllerProcessing(row.controller)) ||
    rows.find((row) =>
      isRobotControllerAwake(row.controller, snapshotAtMs, nowMs),
    ) ||
    rows[0] ||
    null
  )
}

function formatRobotSleepCountdown(seconds: number | null | undefined) {
  const safeSeconds = Math.max(0, Math.ceil(Number(seconds || 0)))
  if (safeSeconds < 60) {
    return `${safeSeconds}s`
  }

  const minutes = Math.floor(safeSeconds / 60)
  const remainder = safeSeconds % 60
  return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`
}

function RobotSleepCountdownRing({
  seconds,
  totalSeconds,
  className = "",
}: {
  seconds: number | null | undefined
  totalSeconds: number | null | undefined
  className?: string
}) {
  const safeSeconds = Math.max(0, Math.ceil(Number(seconds || 0)))
  const safeTotal = Math.max(
    1,
    Math.ceil(Number(totalSeconds || safeSeconds || 1)),
  )
  const progress = Math.min(1, safeSeconds / safeTotal)
  const radius = 7
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - progress)

  return (
    <span
      className={`relative inline-flex size-6 shrink-0 items-center justify-center ${className}`}
      aria-hidden="true"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        className="absolute inset-0 -rotate-90"
      >
        <circle
          cx="10"
          cy="10"
          r={radius}
          fill="none"
          strokeWidth="2.2"
          className="stroke-current opacity-20"
        />
        <circle
          cx="10"
          cy="10"
          r={radius}
          fill="none"
          strokeWidth="2.2"
          strokeLinecap="round"
          className="stroke-current transition-[stroke-dashoffset] duration-700 ease-linear"
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: dashOffset,
          }}
        />
      </svg>
      <span className="font-mono text-[9px] leading-none">{safeSeconds}</span>
    </span>
  )
}

function getRobotConversationLabel(
  controller: RobotConversationControllerStatus,
) {
  return (
    controller.conversation_key ||
    `${controller.conversation_type}:${controller.conversation_id}`
  )
}

function RobotSleepStatusBadge({
  data,
  snapshotAtMs,
  nowMs,
}: {
  data: ItemRobotControllerStatusResponse | undefined
  isFetching: boolean
  snapshotAtMs: number
  nowMs: number
}) {
  const { t } = useI18n()
  if (!data) {
    return null
  }
  if (data.count === 0) {
    return (
      <Badge variant="outline" className="border-slate-500/40 text-slate-500">
        <Bot className="mr-1 size-3" />
        {t("items.detail.qqUnbound")}
      </Badge>
    )
  }

  const enabledRobotCount = getEnabledRobotCount(data)
  if (enabledRobotCount === 0) {
    return (
      <Badge variant="outline" className="border-slate-500/40 text-slate-500">
        <Bot className="mr-1 size-3" />
        {t("items.detail.qqDisabled")}
      </Badge>
    )
  }

  const latest = getLatestRobotControllerRow(data, snapshotAtMs, nowMs)
  const remainingSeconds = getRobotControllerSecondsRemaining(
    latest?.controller,
    snapshotAtMs,
    nowMs,
  )
  const isProcessing = isRobotControllerProcessing(latest?.controller)
  const isAwake = isRobotControllerAwake(
    latest?.controller,
    snapshotAtMs,
    nowMs,
  )
  const label = isProcessing
    ? t("items.detail.qqProcessing")
    : isAwake
      ? t("items.detail.qqAwakeCountdown", {
          time: formatRobotSleepCountdown(remainingSeconds),
        })
      : latest
        ? t("items.detail.qqSleeping")
        : t("items.detail.qqWaitingWake")
  const badgeClass = isProcessing
    ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-600 dark:text-cyan-300"
    : isAwake
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      : "border-slate-500/40 bg-slate-500/10 text-slate-600 dark:text-slate-300"

  return (
    <Badge variant="outline" className={badgeClass}>
      {isProcessing ? (
        <Loader2 className="mr-1 size-3 animate-spin" />
      ) : isAwake ? (
        <RobotSleepCountdownRing
          className="mr-1"
          seconds={remainingSeconds}
          totalSeconds={latest?.robot.reply_context_window_seconds}
        />
      ) : (
        <Moon className="mr-1 size-3" />
      )}
      {label}
    </Badge>
  )
}

function RobotSleepTerminalLine({
  data,
  snapshotAtMs,
  nowMs,
}: {
  data: ItemRobotControllerStatusResponse | undefined
  isFetching: boolean
  snapshotAtMs: number
  nowMs: number
}) {
  const { t } = useI18n()
  if (!data) {
    return null
  }
  if (data.count === 0) {
    return (
      <div className="mb-3 flex min-h-9 flex-wrap items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs text-slate-300">
        <Bot className="size-3.5 text-slate-400" />
        <span className="font-medium text-slate-200">QQ</span>
        <span className="rounded-full bg-slate-700/70 px-2 py-0.5 font-medium text-slate-300">
          {t("items.detail.qqUnbound")}
        </span>
      </div>
    )
  }

  const enabledRobotCount = getEnabledRobotCount(data)
  const latest = getLatestRobotControllerRow(data, snapshotAtMs, nowMs)
  const fallbackRobot = data.robots.find(
    (robot) => robot.is_enabled && robot.allow_chat,
  )
  const remainingSeconds = getRobotControllerSecondsRemaining(
    latest?.controller,
    snapshotAtMs,
    nowMs,
  )
  const isProcessing = isRobotControllerProcessing(latest?.controller)
  const isAwake = isRobotControllerAwake(
    latest?.controller,
    snapshotAtMs,
    nowMs,
  )
  const statusText =
    enabledRobotCount === 0
      ? t("items.detail.qqDisabled")
      : isProcessing
        ? t("items.detail.qqProcessing")
        : isAwake
          ? t("items.detail.qqAwake")
          : latest
            ? t("items.detail.qqSleeping")
            : t("items.detail.qqWaitingWake")
  const statusClass = isProcessing
    ? "bg-cyan-500/15 text-cyan-300"
    : isAwake
      ? "bg-emerald-500/15 text-emerald-300"
      : "bg-slate-700/70 text-slate-300"

  return (
    <div className="mb-3 flex min-h-9 flex-wrap items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs text-slate-300">
      <Bot className="size-3.5 text-cyan-300" />
      <span className="font-medium text-slate-200">
        {latest?.robot.robot_name || fallbackRobot?.robot_name || "QQ"}
      </span>
      <span className={`rounded-full px-2 py-0.5 font-medium ${statusClass}`}>
        {statusText}
      </span>
      {latest ? (
        <span className="font-mono text-slate-400">
          {getRobotConversationLabel(latest.controller)}
        </span>
      ) : null}
      {isProcessing ? (
        <span className="inline-flex items-center gap-1 font-mono text-cyan-300">
          <Loader2 className="size-3 animate-spin" />
          {t("items.detail.qqProcessing")}
        </span>
      ) : isAwake ? (
        <span className="inline-flex items-center gap-1 font-mono text-emerald-300">
          <RobotSleepCountdownRing
            seconds={remainingSeconds}
            totalSeconds={latest?.robot.reply_context_window_seconds}
          />
          {t("items.detail.qqSleepIn", {
            time: formatRobotSleepCountdown(remainingSeconds),
          })}
        </span>
      ) : null}
    </div>
  )
}

function BackgroundJobsPanel({
  jobs,
  isOpen,
  onOpenChange,
  isFetching,
  onRefresh,
  onCancel,
  cancelingJobId,
  daemonOnline,
  error,
}: {
  jobs: BackgroundJob[]
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  isFetching: boolean
  onRefresh: () => void
  onCancel: (jobId: string) => void
  cancelingJobId: string | null
  daemonOnline: boolean
  error?: string | null
}) {
  const count = jobs.length

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/70 text-xs text-slate-300">
      <div className="flex h-10 items-center justify-between gap-2 px-3">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={isOpen}
          onClick={() => onOpenChange(!isOpen)}
        >
          <ChevronRight
            className={`size-4 shrink-0 text-slate-500 transition-transform ${isOpen ? "rotate-90" : ""}`}
          />
          <Server className="size-3.5 shrink-0 text-blue-300" />
          <span className="truncate font-medium text-slate-200">后台 Jobs</span>
          <Badge
            variant="outline"
            className="h-5 border-zinc-700 bg-zinc-900 px-1.5 font-mono text-[10px] text-slate-300"
          >
            {count}
          </Badge>
          {count > 0 ? (
            <span className="hidden truncate font-mono text-[11px] text-slate-500 sm:inline">
              {shortenJobCommand(jobs[0]?.command || "")}
            </span>
          ) : null}
        </button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-slate-400 hover:bg-zinc-800 hover:text-slate-100"
          onClick={onRefresh}
          disabled={!daemonOnline || isFetching}
          title="刷新后台 Jobs"
        >
          <RefreshCw
            className={`size-3.5 ${isFetching ? "animate-spin" : ""}`}
          />
          <span className="sr-only">刷新后台 Jobs</span>
        </Button>
      </div>

      {isOpen ? (
        <div className="border-t border-zinc-800 px-3 py-2">
          {!daemonOnline ? (
            <div className="rounded-md border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-slate-500">
              Daemon 未连接，暂时看不到后台 Jobs。
            </div>
          ) : error ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-200">
              {error}
            </div>
          ) : count === 0 ? (
            <div className="rounded-md border border-dashed border-zinc-800 bg-zinc-900/40 px-3 py-2 text-slate-500">
              没有运行中的后台 Job。
            </div>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => {
                const isCanceling = cancelingJobId === job.job_id
                const cancelDisabled =
                  isCanceling || Boolean(job.cancel_requested)
                return (
                  <div
                    key={job.job_id}
                    className="rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2"
                  >
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] text-blue-300">
                            {job.job_id}
                          </span>
                          <span className="rounded-full bg-zinc-800 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                            {formatJobElapsed(job.elapsed_seconds)}
                          </span>
                          {job.cancel_requested ? (
                            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-300">
                              取消中
                            </span>
                          ) : null}
                        </div>
                        <div className="break-all font-mono text-[11px] leading-5 text-slate-300">
                          {shortenJobCommand(job.command)}
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-8 shrink-0 border-red-500/30 bg-red-500/10 px-2.5 text-xs text-red-300 hover:bg-red-500/20 hover:text-red-200"
                        onClick={() => onCancel(job.job_id)}
                        disabled={cancelDisabled}
                      >
                        {isCanceling ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Square className="size-3.5" />
                        )}
                        取消
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}

function getRobotTriggerLabel(trigger: string) {
  switch (trigger) {
    case "mention_bot":
      return "@唤醒"
    case "reply_to_bot":
      return "回复唤醒"
    case "active_chat_window":
      return "窗口延续"
    case "pending_queue":
      return "队列"
    case "background_job":
      return "后台 Job"
    case "reply_ticket":
      return "待回复"
    case "private":
      return "私聊"
    default:
      return trigger || "消息"
  }
}

function getReplyTicketStatusLabel(status: string | undefined) {
  switch (status) {
    case "running":
      return "处理中"
    case "completed":
      return "待发送"
    case "sending":
      return "发送中"
    case "failed":
      return "发送失败"
    default:
      return "待处理"
  }
}

function formatPendingReplyTime(value: string, localeTag: string) {
  const timestamp = Date.parse(value || "")
  if (!Number.isFinite(timestamp)) {
    return ""
  }
  return new Intl.DateTimeFormat(localeTag, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp)
}

function RobotPendingRepliesPanel({
  data,
  isOpen,
  onOpenChange,
  isFetching,
  localeTag,
}: {
  data: ItemRobotControllerStatusResponse | undefined
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  isFetching: boolean
  localeTag: string
}) {
  const rows = getRobotPendingReplyRows(data)
  const count = rows.length

  if (!data || data.count === 0) {
    return null
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card/80">
      <button
        type="button"
        className="flex h-10 w-full items-center justify-between gap-3 px-3 text-left text-sm"
        onClick={() => onOpenChange(!isOpen)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <MessageSquare className="size-4 shrink-0 text-cyan-500 dark:text-cyan-300" />
          <span className="truncate font-medium">待回复</span>
          <Badge
            variant="outline"
            className={
              count > 0
                ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300"
                : "border-slate-500/30 text-muted-foreground"
            }
          >
            {count}
          </Badge>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {isFetching ? (
            <RefreshCw className="size-3 animate-spin text-muted-foreground" />
          ) : null}
          <ChevronRight
            className={`size-4 text-muted-foreground transition-transform ${isOpen ? "rotate-90" : ""}`}
          />
        </span>
      </button>

      {isOpen ? (
        <div className="max-h-[16rem] overflow-y-auto border-t border-border/60 px-3 py-2">
          {count === 0 ? (
            <div className="py-4 text-center text-xs text-muted-foreground">
              暂无待回复消息
            </div>
          ) : (
            <div className="space-y-2">
              {rows.slice(0, 5).map(({ robot, controller, message }) => (
                <div
                  key={`${robot.robot_id}:${controller.conversation_key}:${message.reply_ticket_id || message.pending_reply_id || message.index}:${message.enqueued_at}`}
                  className="rounded-lg border border-border/50 bg-muted/20 px-2.5 py-2"
                >
                  <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2 text-[11px]">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <Bot className="size-3 shrink-0 text-cyan-500 dark:text-cyan-300" />
                      <span className="truncate font-medium text-foreground/90">
                        {robot.robot_name}
                      </span>
                      <span className="truncate font-mono text-muted-foreground">
                        {getRobotConversationLabel(controller)}
                      </span>
                    </div>
                    <span className="shrink-0 font-mono text-muted-foreground">
                      {formatPendingReplyTime(message.enqueued_at, localeTag)}
                    </span>
                  </div>
                  <div className="mb-1 flex min-w-0 items-center gap-1.5 text-[11px]">
                    <Badge
                      variant="secondary"
                      className="h-5 px-1.5 text-[10px]"
                    >
                      {getRobotTriggerLabel(message.trigger_reason)}
                    </Badge>
                    {message.reply_ticket_status ? (
                      <Badge
                        variant="outline"
                        className={`h-5 px-1.5 text-[10px] ${
                          message.reply_ticket_status === "failed"
                            ? "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-300"
                            : "border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300"
                        }`}
                      >
                        {getReplyTicketStatusLabel(message.reply_ticket_status)}
                      </Badge>
                    ) : null}
                    {message.task_request_id ? (
                      <span className="truncate font-mono text-[10px] text-muted-foreground">
                        plan {message.task_request_id.slice(0, 8)}
                      </span>
                    ) : null}
                    <span className="truncate text-muted-foreground">
                      {message.sender_label || message.sender_key}
                    </span>
                  </div>
                  <div className="line-clamp-2 break-words text-xs leading-5 text-foreground/90">
                    {message.message_preview || "[空消息]"}
                  </div>
                  {message.workflow_objective ? (
                    <div className="mt-2 border-t border-border/50 pt-2 text-[11px]">
                      <div className="flex min-w-0 items-start gap-2">
                        <span className="shrink-0 font-medium text-cyan-700 dark:text-cyan-300">
                          主任务
                        </span>
                        <span className="line-clamp-2 text-foreground/90">
                          {message.workflow_objective}
                        </span>
                      </div>
                      {message.workflow_current_step ? (
                        <div className="mt-1 flex min-w-0 items-start gap-2">
                          <span className="shrink-0 text-muted-foreground">
                            当前
                          </span>
                          <span className="line-clamp-2 font-medium text-foreground/80">
                            {message.workflow_current_step}
                          </span>
                        </div>
                      ) : null}
                      {message.workflow_steps?.length ? (
                        <div className="mt-2 space-y-1">
                          {message.workflow_steps.slice(0, 5).map((step) => (
                            <div
                              key={step.step_id}
                              className="flex min-w-0 items-center gap-1.5 text-[10px]"
                            >
                              {step.status === "completed" ? (
                                <Check className="size-3 shrink-0 text-emerald-500" />
                              ) : step.status === "running" ? (
                                <Loader2 className="size-3 shrink-0 animate-spin text-cyan-500" />
                              ) : step.status === "failed" ? (
                                <AlertCircle className="size-3 shrink-0 text-red-500" />
                              ) : (
                                <Square className="size-3 shrink-0 text-muted-foreground" />
                              )}
                              <span className="truncate text-muted-foreground">
                                {step.title}
                              </span>
                              {step.recovery ? (
                                <span className="shrink-0 text-amber-600 dark:text-amber-300">
                                  恢复步骤
                                </span>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {message.workflow_blocker ? (
                        <div className="mt-1 line-clamp-2 text-red-600 dark:text-red-300">
                          {message.workflow_blocker}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {message.command_preview &&
                  message.command_preview !== message.message_preview ? (
                    <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                      task: {message.command_preview}
                    </div>
                  ) : null}
                  {message.delivery_error ? (
                    <div className="mt-1 line-clamp-2 text-[10px] text-red-600 dark:text-red-300">
                      {message.delivery_error}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}

function RobotConversationDebugTable({
  data,
  isFetching,
  snapshotAtMs,
  nowMs,
}: {
  data: ItemRobotControllerStatusResponse | undefined
  isFetching: boolean
  snapshotAtMs: number
  nowMs: number
}) {
  const { t } = useI18n()
  const rows = getRobotControllerRows(data)

  return (
    <div className="mb-3 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/70 text-xs text-slate-300">
      <div className="flex h-9 items-center justify-between border-b border-zinc-800 px-3">
        <div className="flex min-w-0 items-center gap-2 font-medium text-slate-200">
          <Bot className="size-3.5 shrink-0 text-cyan-300" />
          <span className="truncate">
            {t("items.detail.qqConversationDebug")}
          </span>
        </div>
        {isFetching ? (
          <RefreshCw className="size-3 animate-spin text-slate-500" />
        ) : null}
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-2 font-mono text-[11px] text-slate-500">
          {t("items.detail.qqNoConversations")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] table-fixed border-collapse text-left font-mono text-[11px]">
            <thead className="bg-zinc-900/80 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <tr>
                <th className="w-[9rem] px-3 py-2 font-medium">
                  {t("robots.pageTitle")}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t("items.detail.qqConversation")}
                </th>
                <th className="w-[7rem] px-3 py-2 font-medium">
                  {t("common.status")}
                </th>
                <th className="w-[8rem] px-3 py-2 font-medium">
                  {t("items.detail.qqCountdown")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ robot, controller }) => {
                const isProcessing = isRobotControllerProcessing(controller)
                const isAwake = isRobotControllerAwake(
                  controller,
                  snapshotAtMs,
                  nowMs,
                )
                const remainingSeconds = getRobotControllerSecondsRemaining(
                  controller,
                  snapshotAtMs,
                  nowMs,
                )
                const statusLabel = isProcessing
                  ? t("items.detail.qqProcessing")
                  : isAwake
                    ? t("items.detail.qqAwake")
                    : t("items.detail.qqSleeping")
                const statusClass = isProcessing
                  ? "bg-cyan-500/15 text-cyan-300"
                  : isAwake
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-slate-700/70 text-slate-300"

                return (
                  <tr
                    key={`${robot.robot_id}:${controller.conversation_key}`}
                    className="border-t border-zinc-900/90"
                  >
                    <td className="truncate px-3 py-2 text-slate-300">
                      {robot.robot_name}
                    </td>
                    <td className="truncate px-3 py-2 text-slate-400">
                      {getRobotConversationLabel(controller)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-flex h-6 min-w-20 items-center justify-center rounded-full px-2 font-sans text-[11px] font-medium ${statusClass}`}
                      >
                        {isProcessing ? (
                          <Loader2 className="mr-1 size-3 animate-spin" />
                        ) : isAwake ? (
                          <Check className="mr-1 size-3" />
                        ) : (
                          <Moon className="mr-1 size-3" />
                        )}
                        {statusLabel}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-400">
                      <span className="inline-flex h-6 items-center gap-1.5">
                        {isAwake ? (
                          <RobotSleepCountdownRing
                            seconds={remainingSeconds}
                            totalSeconds={robot.reply_context_window_seconds}
                          />
                        ) : isProcessing ? (
                          <Loader2 className="size-3 animate-spin text-cyan-300" />
                        ) : (
                          <Moon className="size-3 text-slate-500" />
                        )}
                        <span>
                          {isAwake
                            ? formatRobotSleepCountdown(remainingSeconds)
                            : isProcessing
                              ? t("items.detail.qqProcessing")
                              : "0s"}
                        </span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
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
  const [copiedText, copy] = useCopyToClipboard()
  const { data: plugins } = useQuery({
    ...getPluginsQueryOptions(),
    enabled: Boolean(item.id),
  })
  const terminalWsPluginEnabled = isPluginEnabled(
    plugins,
    "termman.terminal_ws",
  )
  const robotPluginEnabled = isPluginEnabled(plugins, "termman.robot")
  const {
    data: robotControllerStatus,
    dataUpdatedAt: robotControllerStatusUpdatedAt,
    isFetching: isFetchingRobotControllerStatus,
  } = useQuery({
    queryKey: getItemRobotControllerStatusQueryKey(item.id),
    queryFn: () => getItemRobotControllerStatus(item.id),
    enabled: Boolean(item.id && robotPluginEnabled),
    refetchInterval: (query) => {
      if (query.state.error) {
        return 10_000
      }
      const data = query.state.data as
        | ItemRobotControllerStatusResponse
        | undefined
      if (!data || data.count === 0) {
        return 15_000
      }
      return hasActiveRobotController(data) ? 2_500 : 10_000
    },
    retry: false,
  })
  const [robotCountdownNowMs, setRobotCountdownNowMs] = useState(() =>
    Date.now(),
  )
  const robotControllerActive = hasActiveRobotController(robotControllerStatus)

  useEffect(() => {
    setRobotCountdownNowMs(Date.now())
    if (!robotControllerActive) {
      return
    }

    const timer = window.setInterval(() => {
      setRobotCountdownNowMs(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [robotControllerActive])

  const [command, setCommand] = useState("")
  const [activeTab, setActiveTab] = useState<ItemDetailTab>("terminal")
  const [visitedTabs, setVisitedTabs] = useState<Set<ItemDetailTab>>(
    () => new Set<ItemDetailTab>(["terminal"]),
  )
  const outputRef = useRef<HTMLDivElement>(null)
  const terminalConnectedRef = useRef(false)
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
  const [terminalWsServers, setTerminalWsServers] = useState<
    TerminalWebSocketServerStatus[]
  >([])
  const [terminalWsForm, setTerminalWsForm] = useState(() =>
    createTerminalWsForm(item.title),
  )
  const [isLoadingTerminalWsServers, setIsLoadingTerminalWsServers] =
    useState(false)
  const [isCreatingTerminalWsServer, setIsCreatingTerminalWsServer] =
    useState(false)
  const [terminalWsActionId, setTerminalWsActionId] = useState<string | null>(
    null,
  )
  const [jobsPanelOpen, setJobsPanelOpen] = useState(false)
  const [pendingRepliesPanelOpen, setPendingRepliesPanelOpen] = useState(false)
  const [jobCancelId, setJobCancelId] = useState<string | null>(null)
  const [itemAction, setItemAction] = useState<
    "start" | "stop" | "restart" | null
  >(null)
  const pendingReplyCount = useMemo(
    () => getRobotPendingReplyCount(robotControllerStatus),
    [robotControllerStatus],
  )
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
  const websocketTabVisited = visitedTabs.has("websocket")
  const currentItemId = item.id
  const currentItemTitle = item.title

  useEffect(() => {
    if (!currentItemId) {
      return
    }
    setActiveTab("terminal")
    setVisitedTabs(new Set<ItemDetailTab>(["terminal"]))
    setTerminalWsForm(createTerminalWsForm(currentItemTitle))
    setTerminalWsServers([])
    setJobsPanelOpen(false)
    setPendingRepliesPanelOpen(false)
    setJobCancelId(null)
  }, [currentItemId, currentItemTitle])

  useEffect(() => {
    if (pendingReplyCount > 0) {
      setPendingRepliesPanelOpen(true)
    }
  }, [pendingReplyCount])

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
    data: backgroundJobs,
    isFetching: isFetchingBackgroundJobs,
    refetch: refetchBackgroundJobs,
  } = useQuery({
    queryKey: ["items", "jobs", item.id],
    queryFn: () => requestItemJobs<BackgroundJobsResponse>(item.id),
    enabled: Boolean(shouldConnect),
    refetchInterval: (query) => {
      if (jobsPanelOpen) {
        return 2_000
      }
      const data = query.state.data as BackgroundJobsResponse | undefined
      return data?.jobs?.length ? 5_000 : 15_000
    },
    retry: false,
  })

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
    onConnected: () => {
      if (!terminalConnectedRef.current) {
        showSuccessToast(t("items.detail.terminalConnected"))
      }
      terminalConnectedRef.current = true
    },
    onDisconnected: () => {
      terminalConnectedRef.current = false
    },
    onError: (error) => {
      terminalConnectedRef.current = false
      showErrorToast(t("items.detail.terminalError", { error }))
    },
  })
  const terminalOutputGroups = useMemo(
    () => buildTerminalOutputGroups(output),
    [output],
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      if (outputRef.current) {
        outputRef.current.scrollTop = outputRef.current.scrollHeight
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [output])

  const refreshItemDetail = useCallback(async () => {
    const refreshed = (await ItemsService.readItem({
      id: item.id,
    })) as ItemWithExtras
    queryClient.setQueryData(getItemQueryOptions(item.id).queryKey, refreshed)
    await queryClient.invalidateQueries({ queryKey: ["items"] })
    return refreshed
  }, [item.id, queryClient])

  const waitForTerminalReady = useCallback(async () => {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const refreshed = await refreshItemDetail()
      if (refreshed.status === "running" && refreshed.daemon_online) {
        return true
      }
      await sleep(500)
    }
    return false
  }, [refreshItemDetail])

  const handleStartItem = async () => {
    setItemAction("start")
    try {
      const result = await ItemsService.startItem({ id: item.id })
      const ready = await waitForTerminalReady()
      showSuccessToast(result.message || t("items.detail.started"))
      if (ready) {
        reconnect(true)
      } else {
        showErrorToast("终端启动成功，但前端还没读到可连接状态，请稍后刷新。")
      }
    } catch (error) {
      console.error("Failed to start item:", error)
      showErrorToast(t("items.detail.startFailed"))
    } finally {
      setItemAction(null)
    }
  }

  const handleStopItem = async () => {
    setItemAction("stop")
    try {
      disconnect()
      const result = await ItemsService.stopItem({ id: item.id })
      await refreshItemDetail()
      showSuccessToast(result.message || t("items.detail.stopped"))
    } catch (error) {
      console.error("Failed to stop item:", error)
      showErrorToast(t("items.detail.stopFailed"))
    } finally {
      setItemAction(null)
    }
  }

  const handleRestartItem = async () => {
    setItemAction("restart")
    try {
      disconnect()
      const result = await ItemsService.restartItem({ id: item.id })
      const ready = await waitForTerminalReady()
      showSuccessToast(result.message || t("items.detail.restarted"))
      if (ready) {
        reconnect(true)
      } else {
        showErrorToast("终端重启成功，但前端还没读到可连接状态，请稍后刷新。")
      }
    } catch (error) {
      console.error("Failed to restart item:", error)
      showErrorToast(t("items.detail.restartFailed"))
    } finally {
      setItemAction(null)
    }
  }

  const handleSendCommand = () => {
    if (command.trim()) {
      sendCommand(command)
      setCommand("")
    }
  }

  const handleCancelBackgroundJob = async (jobId: string) => {
    setJobCancelId(jobId)
    try {
      await requestItemJobs<{ success: boolean }>(
        item.id,
        `/${encodeURIComponent(jobId)}/cancel`,
        { method: "POST" },
      )
      await refetchBackgroundJobs()
      showSuccessToast("后台 Job 已取消")
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "后台 Job 取消失败",
      )
    } finally {
      setJobCancelId(null)
    }
  }

  const loadTerminalWsServers = useCallback(async () => {
    if (!terminalWsPluginEnabled) {
      setTerminalWsServers([])
      return
    }
    setIsLoadingTerminalWsServers(true)
    try {
      const data =
        await requestTerminalWebSocket<TerminalWebSocketServerListResponse>(
          item.id,
        )
      setTerminalWsServers(data.servers || [])
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : "Failed to load WebSocket servers",
      )
    } finally {
      setIsLoadingTerminalWsServers(false)
    }
  }, [item.id, showErrorToast, terminalWsPluginEnabled])

  const handleCreateTerminalWsServer = async () => {
    const name = terminalWsForm.name.trim()
    if (!name) {
      showErrorToast("Name is required")
      return
    }

    const port = terminalWsForm.port.trim()
      ? Number(terminalWsForm.port.trim())
      : null
    if (
      port !== null &&
      (!Number.isInteger(port) || port < 1 || port > 65535)
    ) {
      showErrorToast("Port must be 1-65535")
      return
    }

    const heartbeatInterval = terminalWsForm.heartbeat_interval.trim()
      ? Number(terminalWsForm.heartbeat_interval.trim())
      : null
    if (
      heartbeatInterval !== null &&
      (!Number.isFinite(heartbeatInterval) ||
        heartbeatInterval < 1 ||
        heartbeatInterval > 300)
    ) {
      showErrorToast("Heartbeat must be 1-300 seconds")
      return
    }

    setIsCreatingTerminalWsServer(true)
    try {
      await requestTerminalWebSocket<TerminalWebSocketServerStatus>(
        item.id,
        "",
        {
          method: "POST",
          body: JSON.stringify({
            name,
            host: terminalWsForm.host.trim() || null,
            port,
            token: terminalWsForm.token.trim() || null,
            heartbeat_interval: heartbeatInterval,
            message_format: terminalWsForm.message_format,
          }),
        },
      )
      setTerminalWsForm(createTerminalWsForm(item.title))
      await loadTerminalWsServers()
      showSuccessToast("WebSocket server created")
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : "Failed to create WebSocket server",
      )
    } finally {
      setIsCreatingTerminalWsServer(false)
    }
  }

  const handleTerminalWsAction = async (
    serverId: string,
    action: "start" | "stop" | "delete",
  ) => {
    setTerminalWsActionId(serverId)
    try {
      if (action === "delete") {
        await requestTerminalWebSocket<{ success: boolean }>(
          item.id,
          `/${serverId}`,
          { method: "DELETE" },
        )
      } else {
        await requestTerminalWebSocket<TerminalWebSocketServerStatus>(
          item.id,
          `/${serverId}/${action}`,
          { method: "POST" },
        )
      }
      await loadTerminalWsServers()
      const actionLabel =
        action === "start"
          ? "started"
          : action === "stop"
            ? "stopped"
            : "deleted"
      showSuccessToast(`WebSocket server ${actionLabel}`)
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : `Failed to ${action} WebSocket server`,
      )
    } finally {
      setTerminalWsActionId(null)
    }
  }

  const handleCopyTerminalWsUrl = async (value: string) => {
    await copy(value)
    showSuccessToast("Copied")
  }

  useEffect(() => {
    if (!terminalWsPluginEnabled) {
      setTerminalWsServers([])
      return
    }
    if (!websocketTabVisited) {
      return
    }
    void loadTerminalWsServers()
  }, [loadTerminalWsServers, terminalWsPluginEnabled, websocketTabVisited])

  useEffect(() => {
    if (!terminalWsPluginEnabled && activeTab === "websocket") {
      setActiveTab("terminal")
    }
  }, [activeTab, terminalWsPluginEnabled])

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

  const updateItemCaches = useCallback(
    (updatedItem: ItemPublic) => {
      const cachedItem = updatedItem as ItemWithExtras

      queryClient.setQueryData<ItemWithExtras>(
        ["items", "detail", updatedItem.id],
        (current) => ({ ...(current || {}), ...cachedItem }),
      )
      queryClient.setQueryData<ItemsResponse | undefined>(
        ["items"],
        (current) =>
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
    },
    [queryClient],
  )

  const handleSyncInputFilterRules = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["items", "detail", item.id],
    })
    showSuccessToast("已同步后端过滤规则")
  }

  const handleApplyCommonInputNoiseRule = (
    preset: (typeof COMMON_INPUT_NOISE_RULES)[number],
  ) => {
    setInputFilterEnabled(true)
    setInputFilterRules((current) =>
      mergeFilterRule(current, preset.key, preset.rule),
    )
    showSuccessToast(`已添加规则：${preset.label}`)
  }

  useEffect(() => {
    if (activeTab !== "filters") {
      return
    }
    void queryClient.invalidateQueries({
      queryKey: ["items", "detail", item.id],
    })
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({
        queryKey: ["items", "detail", item.id],
      })
    }, 5000)
    return () => window.clearInterval(timer)
  }, [activeTab, item.id, queryClient])

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
                    disabled={itemAction !== null}
                  >
                    {itemAction === "start" ? (
                      <Loader2 className="mr-1 size-3 animate-spin" />
                    ) : null}
                    {t("items.detail.start")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 min-w-20 px-3.5 text-xs"
                    onClick={handleStopItem}
                    disabled={itemAction !== null}
                  >
                    {itemAction === "stop" ? (
                      <Loader2 className="mr-1 size-3 animate-spin" />
                    ) : null}
                    {t("items.detail.stop")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 min-w-20 px-3.5 text-xs"
                    onClick={handleRestartItem}
                    disabled={itemAction !== null}
                  >
                    {itemAction === "restart" ? (
                      <Loader2 className="mr-1 size-3 animate-spin" />
                    ) : null}
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
                {terminalWsPluginEnabled && (
                  <TabsTrigger value="websocket">WebSocket Server</TabsTrigger>
                )}
                {robotPluginEnabled && (
                  <TabsTrigger value="qq-debug">
                    {t("items.detail.qqConversationDebug")}
                  </TabsTrigger>
                )}
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
                <TabsTrigger value="scheduled-tasks">定时任务</TabsTrigger>
              </TabsList>
            </div>

            {terminalWsPluginEnabled && (
              <TabsContent value="websocket" className="space-y-4">
                {hasVisitedTab("websocket") ? (
                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex items-start gap-2">
                        <Server className="mt-1 size-5 text-blue-500" />
                        <div>
                          <h2 className="text-base font-semibold">
                            WebSocket Server
                          </h2>
                          <p className="text-xs text-muted-foreground">
                            {item.title}
                          </p>
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 w-fit px-3 text-xs"
                        onClick={() => void loadTerminalWsServers()}
                        disabled={isLoadingTerminalWsServers}
                      >
                        <RefreshCw
                          className={`size-3.5 ${isLoadingTerminalWsServers ? "animate-spin" : ""}`}
                        />
                        Refresh
                      </Button>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-12">
                      <div className="space-y-1.5 xl:col-span-3">
                        <Label htmlFor="terminal-ws-name">Name</Label>
                        <Input
                          id="terminal-ws-name"
                          value={terminalWsForm.name}
                          onChange={(event) =>
                            setTerminalWsForm((current) => ({
                              ...current,
                              name: event.target.value,
                            }))
                          }
                          className="h-9"
                        />
                      </div>
                      <div className="space-y-1.5 xl:col-span-2">
                        <Label htmlFor="terminal-ws-host">Host</Label>
                        <Input
                          id="terminal-ws-host"
                          value={terminalWsForm.host}
                          onChange={(event) =>
                            setTerminalWsForm((current) => ({
                              ...current,
                              host: event.target.value,
                            }))
                          }
                          placeholder="0.0.0.0"
                          className="h-9 font-mono"
                        />
                      </div>
                      <div className="space-y-1.5 xl:col-span-1">
                        <Label htmlFor="terminal-ws-port">Port</Label>
                        <Input
                          id="terminal-ws-port"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          value={terminalWsForm.port}
                          onChange={(event) =>
                            setTerminalWsForm((current) => ({
                              ...current,
                              port: event.target.value,
                            }))
                          }
                          placeholder="auto"
                          className="h-9 font-mono"
                        />
                      </div>
                      <div className="space-y-1.5 xl:col-span-3">
                        <Label htmlFor="terminal-ws-token">Token</Label>
                        <Input
                          id="terminal-ws-token"
                          value={terminalWsForm.token}
                          onChange={(event) =>
                            setTerminalWsForm((current) => ({
                              ...current,
                              token: event.target.value,
                            }))
                          }
                          placeholder="auto"
                          className="h-9 font-mono"
                        />
                      </div>
                      <div className="space-y-1.5 xl:col-span-1">
                        <Label htmlFor="terminal-ws-heartbeat">Heartbeat</Label>
                        <Input
                          id="terminal-ws-heartbeat"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          value={terminalWsForm.heartbeat_interval}
                          onChange={(event) =>
                            setTerminalWsForm((current) => ({
                              ...current,
                              heartbeat_interval: event.target.value,
                            }))
                          }
                          className="h-9 font-mono"
                        />
                      </div>
                      <div className="space-y-1.5 xl:col-span-1">
                        <Label htmlFor="terminal-ws-format">Format</Label>
                        <Input
                          id="terminal-ws-format"
                          value={terminalWsForm.message_format}
                          disabled
                          className="h-9 font-mono"
                        />
                      </div>
                      <Button
                        type="button"
                        className="h-9 md:self-end xl:col-span-1"
                        onClick={() => void handleCreateTerminalWsServer()}
                        disabled={isCreatingTerminalWsServer}
                      >
                        {isCreatingTerminalWsServer ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Server className="size-4" />
                        )}
                        Create
                      </Button>
                    </div>

                    <div className="mt-4 space-y-2">
                      {isLoadingTerminalWsServers ? (
                        <div className="flex h-20 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                          <Loader2 className="mr-2 size-4 animate-spin" />
                          Loading
                        </div>
                      ) : terminalWsServers.length === 0 ? (
                        <div className="flex h-20 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                          No WebSocket servers
                        </div>
                      ) : (
                        terminalWsServers.map((server) => {
                          const connectionUrl =
                            getTerminalWsConnectionUrl(server)
                          return (
                            <div
                              key={server.server_id}
                              className="rounded-lg border bg-muted/20 p-3"
                            >
                              <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                                <div className="min-w-0 flex-1 space-y-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-medium">
                                      {server.name}
                                    </span>
                                    <Badge
                                      className={
                                        server.running
                                          ? "border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400"
                                          : "border-zinc-500/40 bg-zinc-500/10 text-zinc-600 dark:text-zinc-300"
                                      }
                                    >
                                      {server.running ? "running" : "stopped"}
                                    </Badge>
                                    <Badge variant="secondary">
                                      {server.client_count} clients
                                    </Badge>
                                  </div>
                                  <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 xl:grid-cols-4">
                                    <span className="truncate">
                                      Host:{" "}
                                      <span className="font-mono text-foreground/80">
                                        {server.host}
                                      </span>
                                    </span>
                                    <span>
                                      Port:{" "}
                                      <span className="font-mono text-foreground/80">
                                        {server.port}
                                      </span>
                                    </span>
                                    <span>
                                      Format:{" "}
                                      <span className="font-mono text-foreground/80">
                                        {server.message_format}
                                      </span>
                                    </span>
                                    <span>
                                      Heartbeat:{" "}
                                      <span className="font-mono text-foreground/80">
                                        {server.heartbeat_interval}s
                                      </span>
                                    </span>
                                  </div>
                                  <div className="flex min-w-0 items-center gap-2 rounded-md bg-background/70 px-2 py-1.5">
                                    <span className="min-w-0 flex-1 truncate font-mono text-xs">
                                      {connectionUrl}
                                    </span>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon"
                                      className="size-7 shrink-0"
                                      onClick={() =>
                                        void handleCopyTerminalWsUrl(
                                          connectionUrl,
                                        )
                                      }
                                    >
                                      {copiedText === connectionUrl ? (
                                        <Check className="size-3.5 text-green-500" />
                                      ) : (
                                        <Copy className="size-3.5" />
                                      )}
                                      <span className="sr-only">Copy URL</span>
                                    </Button>
                                  </div>
                                </div>

                                <div className="flex shrink-0 flex-wrap gap-2 xl:justify-end">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant={
                                      server.running ? "outline" : "default"
                                    }
                                    className="h-8 px-3 text-xs"
                                    onClick={() =>
                                      void handleTerminalWsAction(
                                        server.server_id,
                                        server.running ? "stop" : "start",
                                      )
                                    }
                                    disabled={
                                      terminalWsActionId === server.server_id
                                    }
                                  >
                                    {terminalWsActionId === server.server_id ? (
                                      <Loader2 className="size-3.5 animate-spin" />
                                    ) : server.running ? (
                                      <Square className="size-3.5" />
                                    ) : (
                                      <Play className="size-3.5" />
                                    )}
                                    {server.running ? "Stop" : "Start"}
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="destructive"
                                    className="h-8 px-3 text-xs"
                                    onClick={() =>
                                      void handleTerminalWsAction(
                                        server.server_id,
                                        "delete",
                                      )
                                    }
                                    disabled={
                                      terminalWsActionId === server.server_id
                                    }
                                  >
                                    <Trash2 className="size-3.5" />
                                    Delete
                                  </Button>
                                </div>
                              </div>
                            </div>
                          )
                        })
                      )}
                    </div>
                  </section>
                ) : null}
              </TabsContent>
            )}

            <TabsContent value="terminal" className="space-y-4">
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
                          <RobotSleepStatusBadge
                            data={robotControllerStatus}
                            isFetching={isFetchingRobotControllerStatus}
                            snapshotAtMs={robotControllerStatusUpdatedAt}
                            nowMs={robotCountdownNowMs}
                          />
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
                        <RobotSleepTerminalLine
                          data={robotControllerStatus}
                          isFetching={isFetchingRobotControllerStatus}
                          snapshotAtMs={robotControllerStatusUpdatedAt}
                          nowMs={robotCountdownNowMs}
                        />

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
                                terminalOutputGroups.map(
                                  (group, groupIndex) => {
                                    if (group.kind === "job") {
                                      return (
                                        <TerminalJobOutputBlock
                                          key={`job-${groupIndex}-${group.jobId}`}
                                          group={group}
                                        />
                                      )
                                    }

                                    return group.entries.map(
                                      (out, entryIndex) => {
                                        const text = getTerminalOutputText(out)
                                        const isInput = isTerminalInput(
                                          out,
                                          text,
                                        )
                                        const isError = Boolean(out.stderr)
                                        return (
                                          <span
                                            key={`terminal-${groupIndex}-${entryIndex}`}
                                            className={`whitespace-pre ${isError ? "text-red-300" : isInput ? "text-green-400" : "text-blue-300"}`}
                                          >
                                            {text}
                                          </span>
                                        )
                                      },
                                    )
                                  },
                                )
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
                              onClick={() => reconnect()}
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
                                  : item.daemon_online
                                    ? "Daemon 在线，但浏览器控制台还未连接。请点击重试连接。"
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
                            {item.status === "running" && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="mt-2"
                                  onClick={() => reconnect()}
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
                    <div className="flex h-[42rem] flex-col gap-3">
                      <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border bg-card/85 shadow-sm">
                        <ChatPanel itemId={item.id} />
                      </div>
                      {robotPluginEnabled ? (
                        <RobotPendingRepliesPanel
                          data={robotControllerStatus}
                          isOpen={pendingRepliesPanelOpen}
                          onOpenChange={setPendingRepliesPanelOpen}
                          isFetching={isFetchingRobotControllerStatus}
                          localeTag={localeTag}
                        />
                      ) : null}
                    </div>
                  </div>
                </div>
                <div className="mt-4">
                  <BackgroundJobsPanel
                    jobs={backgroundJobs?.jobs || []}
                    isOpen={jobsPanelOpen}
                    onOpenChange={setJobsPanelOpen}
                    isFetching={isFetchingBackgroundJobs}
                    onRefresh={() => void refetchBackgroundJobs()}
                    onCancel={(jobId) => void handleCancelBackgroundJob(jobId)}
                    cancelingJobId={jobCancelId}
                    daemonOnline={Boolean(item.daemon_online)}
                    error={backgroundJobs?.error}
                  />
                </div>
              </section>
            </TabsContent>

            {robotPluginEnabled && (
              <TabsContent value="qq-debug" className="space-y-4">
                {hasVisitedTab("qq-debug") ? (
                  <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                    <RobotConversationDebugTable
                      data={robotControllerStatus}
                      isFetching={isFetchingRobotControllerStatus}
                      snapshotAtMs={robotControllerStatusUpdatedAt}
                      nowMs={robotCountdownNowMs}
                    />
                  </section>
                ) : null}
              </TabsContent>
            )}

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

                    <div className="mb-4 rounded-xl border bg-muted/20 p-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-medium">
                            <Filter className="size-4 text-blue-500" />
                            <span>Agent 噪声过滤规则</span>
                            <Badge variant="outline" className="text-[10px]">
                              {Object.keys(inputFilterRules).length}
                            </Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Agent 通过 MCP
                            写入的规则会显示在下面，也可以手动添加常见噪声。
                          </p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void handleSyncInputFilterRules()}
                        >
                          <RefreshCw className="mr-2 size-4" />
                          同步后端规则
                        </Button>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {COMMON_INPUT_NOISE_RULES.map((preset) => {
                          const applied = hasFilterRule(
                            inputFilterRules,
                            preset.key,
                            preset.rule,
                          )
                          return (
                            <Button
                              key={preset.key}
                              type="button"
                              size="sm"
                              variant={applied ? "secondary" : "outline"}
                              disabled={applied}
                              onClick={() =>
                                handleApplyCommonInputNoiseRule(preset)
                              }
                              title={preset.description}
                            >
                              {applied ? (
                                <Check className="mr-2 size-4" />
                              ) : (
                                <Plus className="mr-2 size-4" />
                              )}
                              {preset.label}
                            </Button>
                          )
                        })}
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
                          <PasswordInput
                            value={configForm.api_key}
                            onChange={(event) =>
                              setConfigForm((current) => ({
                                ...current,
                                api_key: event.target.value,
                              }))
                            }
                            copyable
                            copyLabel={t("common.copyLabel", {
                              label: "Daemon API Key",
                            })}
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

            <TabsContent value="scheduled-tasks">
              {hasVisitedTab("scheduled-tasks") ? (
                <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
                  <ScheduledTasksManager itemId={item.id} />
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
