import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Activity,
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronRight,
  Cpu,
  Gauge,
  HardDrive,
  Network,
  Plug,
  RefreshCw,
  Server,
  Shield,
  Terminal,
  Trash2,
  User,
  Wifi,
  type LucideIcon,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { ItemHandlerAssociationsService, ItemsService } from "@/client/sdk.gen"
import {
  type BridgeHealthResponse,
  getBridgeHealth,
  getBridgeHealthQueryKey,
  getRobotsQueryKey,
  listRobots,
  type RobotRecord,
} from "@/components/Robots/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import useAuth from "@/hooks/useAuth"
import {
  type BackendRuntimeStatsResponse,
  getBackendRuntimeStats,
} from "@/services/runtime"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "数据看板 - TermMan",
      },
    ],
  }),
})

type Subscriber = {
  sid: string
  user_uuid: string
  user_name: string
  ip: string
  type: string
  join_time: number
  last_active_time: number
}

type Item = {
  id: string
  title: string
  description: string | null
  status: string
  owner_id: string
  daemon_id?: string
  daemon_url?: string
  daemon_online?: boolean
  daemon_status?: string
  subscribers?: Subscriber[]
  browser_count?: number
  backend_connected?: boolean
  [key: string]: unknown
}

type Daemon = {
  id: string
  url: string
  online: boolean
  status: string
  items: Item[]
}

type BridgeBotSnapshot = {
  self_id?: string | null
  adapter?: string | null
  class?: string | null
  bot_info?: Record<string, unknown> | null
}

type BridgeRobotStatus = BridgeHealthResponse["robots"][string] & {
  platform?: string | null
  reverse_ws_url?: string | null
  ws_url?: string | null
  bot?: BridgeBotSnapshot | null
  onebot_socket?: Record<string, unknown> | null
  last_platform_event_at?: string | null
  last_message_event_at?: string | null
  error?: string | null
  last_error?: Record<string, unknown> | string | null
}

type ExtendedBridgeHealth = BridgeHealthResponse & {
  checked_at?: string | null
  live?: boolean
  onebot_reverse_ws_url?: string | null
  bots?: BridgeBotSnapshot[]
  backend?: Record<string, unknown>
  connection_errors?: Record<string, unknown>
  ipc_owner?: Record<string, unknown>
}

type KeyValue = {
  label: string
  value: string
  hint?: string
}

const UNKNOWN = "未上报"

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function firstText(...values: Array<string | number | null | undefined>) {
  for (const value of values) {
    if (value === null || value === undefined) {
      continue
    }
    const text = String(value).trim()
    if (text) {
      return text
    }
  }
  return null
}

function displayRecordValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return null
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value)
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否"
  }
  return null
}

function readRecordValue(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
) {
  if (!record) {
    return null
  }
  for (const key of keys) {
    const value = displayRecordValue(record[key])
    if (value) {
      return value
    }
  }
  return null
}

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return UNKNOWN
  }
  if (value < 1024) {
    return `${value} B`
  }

  const units = ["KB", "MB", "GB", "TB"]
  let size = value
  let unitIndex = -1
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }

  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

function formatPercent(
  value: number | null | undefined,
  fallback = "等待采样",
) {
  if (value === null || value === undefined) {
    return fallback
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`
}

function formatFrequency(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return UNKNOWN
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}GHz`
  }
  return `${value.toFixed(0)}MHz`
}

function formatSeconds(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return UNKNOWN
  }
  if (value < 60) {
    return `${Math.round(value)} 秒`
  }
  if (value < 3600) {
    return `${Math.floor(value / 60)} 分 ${Math.round(value % 60)} 秒`
  }
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  return `${hours} 小时 ${minutes} 分`
}

function formatTimestamp(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return UNKNOWN
  }
  return new Date(value * 1000).toLocaleString()
}

function formatDateTime(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return UNKNOWN
  }
  const date =
    typeof value === "number"
      ? new Date(value > 1_000_000_000_000 ? value : value * 1000)
      : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }
  return date.toLocaleString()
}

function formatCollectionScope(value: string | null | undefined) {
  if (value === "parent_process_group") {
    return "后端主进程 + Worker 聚合"
  }
  if (value === "current_process") {
    return "当前后端进程"
  }
  return value || UNKNOWN
}

function statusLabel(status: string | null | undefined) {
  switch (status) {
    case "running":
      return "运行中"
    case "starting":
      return "启动中"
    case "stopping":
      return "停止中"
    case "stopped":
      return "已停止"
    case "error":
      return "错误"
    default:
      return status || "未知"
  }
}

function statusBadgeClass(status: string | null | undefined) {
  switch (status) {
    case "running":
    case "online":
    case "connected":
      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
    case "starting":
    case "stopping":
      return "bg-amber-500/10 text-amber-700 dark:text-amber-300"
    case "error":
    case "offline":
    case "disconnected":
      return "bg-red-500/10 text-red-700 dark:text-red-300"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function groupItemsByDaemon(items: Item[]): Daemon[] {
  const daemonMap: Record<string, Daemon> = {}

  items.forEach((item) => {
    const daemonUrl = item.daemon_url || "unknown-daemon"
    const daemonId = item.daemon_id || daemonUrl

    if (!daemonMap[daemonId]) {
      daemonMap[daemonId] = {
        id: daemonId,
        url: daemonUrl,
        online: item.daemon_online ?? false,
        status: item.daemon_status ?? "unknown",
        items: [],
      }
    }

    daemonMap[daemonId].items.push(item)
  })

  return Object.values(daemonMap)
}

function countSubscribers(items: Item[]) {
  return items.reduce((total, item) => total + (item.subscribers?.length ?? 0), 0)
}

function countBrowsers(items: Item[]) {
  return items.reduce((total, item) => total + (item.browser_count ?? 0), 0)
}

function StatusPill({
  connected,
  label,
}: {
  connected: boolean
  label: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        connected
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "bg-red-500/10 text-red-700 dark:text-red-300"
      }`}
    >
      <span
        className={`size-1.5 rounded-full ${
          connected ? "bg-emerald-500" : "bg-red-500"
        }`}
      />
      {label}
    </span>
  )
}

function MetricTile({
  title,
  value,
  hint,
  icon: Icon,
}: {
  title: string
  value: string
  hint?: string
  icon: LucideIcon
}) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 px-4">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="size-4 text-primary" />
      </CardHeader>
      <CardContent className="px-4">
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
        {hint ? (
          <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function KeyValueGrid({ rows }: { rows: KeyValue[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {rows.map((row) => (
        <div key={row.label} className="min-w-0 border-t pt-3">
          <p className="text-xs text-muted-foreground">{row.label}</p>
          <p className="mt-1 break-words text-sm font-medium">{row.value}</p>
          {row.hint ? (
            <p className="mt-1 break-words text-xs text-muted-foreground">
              {row.hint}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function ResourcePanel({
  title,
  icon: Icon,
  rows,
}: {
  title: string
  icon: LucideIcon
  rows: KeyValue[]
}) {
  return (
    <Card className="gap-4 py-5">
      <CardHeader className="flex flex-row items-center gap-2 px-5">
        <Icon className="size-4 text-primary" />
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-5">
        <div className="space-y-3">
          {rows.map((row) => (
            <div
              key={row.label}
              className="grid grid-cols-[minmax(86px,0.45fr)_1fr] gap-3 text-sm"
            >
              <span className="text-muted-foreground">{row.label}</span>
              <span className="min-w-0 break-words font-medium">
                {row.value}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function ErrorNotice({ title, message }: { title: string; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}

function Dashboard() {
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedDaemons, setExpandedDaemons] = useState<
    Record<string, boolean>
  >({})
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>(
    {},
  )
  const [disconnectDialog, setDisconnectDialog] = useState<{
    open: boolean
    itemId: string
    itemTitle: string
    userUuid: string
    userName: string
    ip: string
  } | null>(null)
  const [disconnecting, setDisconnecting] = useState(false)

  const isAdmin = currentUser?.is_superuser ?? false

  const runtimeQuery = useQuery({
    queryKey: ["dashboard-backend-runtime"],
    queryFn: getBackendRuntimeStats,
    enabled: isAdmin,
    refetchInterval: 5000,
    retry: false,
  })

  const bridgeHealthQuery = useQuery<BridgeHealthResponse>({
    queryKey: getBridgeHealthQueryKey(),
    queryFn: getBridgeHealth,
    refetchInterval: 15000,
    retry: false,
  })

  const robotsQuery = useQuery({
    queryKey: getRobotsQueryKey(),
    queryFn: listRobots,
    refetchInterval: 30000,
    retry: false,
  })

  const fetchItems = useCallback(async () => {
    try {
      setLoading(true)
      const response = await ItemsService.readItems()
      setItems((response as { data: Item[] }).data || [])
    } catch (error) {
      console.error("Failed to fetch items:", error)
      toast.error("读取终端列表失败，请稍后重试。")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleDisconnectUser = async () => {
    if (!disconnectDialog) return

    try {
      setDisconnecting(true)
      await ItemsService.disconnectItemSubscriber({
        id: disconnectDialog.itemId,
        requestBody: {
          user_uuid: disconnectDialog.userUuid,
          ip_address: disconnectDialog.ip,
        },
      })
      toast.success("已断开用户连接。")
      await fetchItems()
    } catch (error) {
      console.error("Failed to disconnect user:", error)
      toast.error("断开用户连接失败，请稍后重试。")
    } finally {
      setDisconnecting(false)
      setDisconnectDialog(null)
    }
  }

  const handleReconnectDaemon = async (daemonId: string) => {
    try {
      const result = (await ItemsService.reconnectDaemon({ daemonId })) as {
        success: boolean
        message: string
      }
      if (result.success) {
        toast.success(result.message)
        await fetchItems()
      } else {
        toast.error(result.message)
      }
    } catch (error) {
      console.error("Failed to reconnect daemon:", error)
      toast.error("重连 Daemon 失败，请稍后重试。")
    }
  }

  const toggleDaemonExpand = (daemonId: string) => {
    setExpandedDaemons((prev) => ({
      ...prev,
      [daemonId]: !prev[daemonId],
    }))
  }

  const toggleItemExpand = (itemId: string) => {
    setExpandedItems((prev) => ({
      ...prev,
      [itemId]: !prev[itemId],
    }))
  }

  const refreshDashboard = async () => {
    await Promise.allSettled([
      fetchItems(),
      runtimeQuery.refetch(),
      bridgeHealthQuery.refetch(),
      robotsQuery.refetch(),
    ])
  }

  const runtime = runtimeQuery.data as BackendRuntimeStatsResponse | undefined
  const bridgeHealth = bridgeHealthQuery.data as ExtendedBridgeHealth | undefined
  const robots = robotsQuery.data?.data ?? []
  const daemons = useMemo(() => groupItemsByDaemon(items), [items])
  const robotMap = useMemo(
    () => new Map(robots.map((robot: RobotRecord) => [robot.id, robot])),
    [robots],
  )

  const itemStats = useMemo(() => {
    const byStatus = new Map<string, number>()
    for (const item of items) {
      byStatus.set(item.status, (byStatus.get(item.status) ?? 0) + 1)
    }
    return {
      total: items.length,
      running: byStatus.get("running") ?? 0,
      error: byStatus.get("error") ?? 0,
      connectedUsers: countSubscribers(items),
      browserConnections: countBrowsers(items),
    }
  }, [items])

  const bridgeRobotEntries = useMemo(
    () =>
      Object.entries(bridgeHealth?.robots ?? {}) as Array<
        [string, BridgeRobotStatus]
      >,
    [bridgeHealth],
  )

  const primaryRobotEntry =
    bridgeRobotEntries.find(([robotId]) => robotId === robots[0]?.id) ??
    bridgeRobotEntries[0]
  const primaryRobotStatus = primaryRobotEntry?.[1]
  const primaryRobotRecord = primaryRobotEntry
    ? robotMap.get(primaryRobotEntry[0])
    : robots[0]
  const primaryBot = primaryRobotStatus?.bot ?? bridgeHealth?.bots?.[0] ?? null
  const primaryBotInfo = isRecord(primaryBot?.bot_info)
    ? primaryBot.bot_info
    : {}
  const primarySocket = isRecord(primaryRobotStatus?.onebot_socket)
    ? primaryRobotStatus.onebot_socket
    : {}

  const robotName =
    firstText(
      primaryRobotRecord?.name,
      readRecordValue(primaryBotInfo, ["username", "name", "nickname"]),
    ) ?? "未配置机器人"
  const robotIdentity =
    firstText(
      primaryRobotStatus?.identity,
      primaryRobotRecord?.app_id,
      primaryBot?.self_id,
      readRecordValue(primaryBotInfo, ["id", "user_id", "self_id"]),
      bridgeHealth?.connected_identities?.[0],
    ) ?? UNKNOWN
  const napcatVersion =
    firstText(
      readRecordValue(primarySocket, [
        "napcat_version",
        "napcatVersion",
        "napcat",
        "version",
      ]),
      readRecordValue(primaryBotInfo, [
        "napcat_version",
        "napcatVersion",
        "version",
      ]),
    ) ?? UNKNOWN
  const qqVersion =
    firstText(
      readRecordValue(primarySocket, [
        "qq_version",
        "qqVersion",
        "client_version",
        "clientVersion",
        "app_version",
        "appVersion",
      ]),
      readRecordValue(primaryBotInfo, [
        "qq_version",
        "qqVersion",
        "client_version",
        "clientVersion",
      ]),
    ) ?? UNKNOWN
  const reverseWsUrl =
    firstText(
      bridgeHealth?.onebot_reverse_ws_url,
      primaryRobotStatus?.reverse_ws_url,
      primaryRobotStatus?.ws_url,
      readRecordValue(primarySocket, ["reverse_ws_url", "ws_url", "server_url"]),
    ) ?? UNKNOWN

  const connectedRobotCount =
    bridgeHealth?.connected_bot_count ??
    bridgeRobotEntries.filter(([, status]) => status.connected).length
  const loadedRobotCount = bridgeHealth?.loaded_robot_count ?? robots.length
  const onlineDaemonCount = daemons.filter((daemon) => daemon.online).length
  const runtimeCpuHint = runtime
    ? `${runtime.aggregate.process_count} 进程 · PID ${runtime.current_pid}`
    : isAdmin
      ? "正在读取后端运行时"
      : "仅管理员可见"

  const systemRows: KeyValue[] = [
    { label: "服务", value: runtime?.service ?? "backend" },
    { label: "主机", value: runtime?.hostname ?? UNKNOWN },
    { label: "系统版本", value: runtime?.platform ?? UNKNOWN },
    { label: "Python 版本", value: runtime?.python_version ?? UNKNOWN },
    { label: "采样时间", value: formatTimestamp(runtime?.sampled_at) },
    {
      label: "后端运行时长",
      value: formatSeconds(runtime?.current_process.uptime_seconds),
    },
    {
      label: "采集范围",
      value: formatCollectionScope(runtime?.collection_scope),
    },
  ]

  const robotRows: KeyValue[] = [
    { label: "NapCat 版本", value: napcatVersion },
    { label: "QQ 版本", value: qqVersion },
    { label: "WebUI 版本", value: UNKNOWN },
    {
      label: "协议",
      value:
        firstText(
          primaryRobotRecord?.protocol,
          primaryRobotRecord?.platform,
          primaryRobotStatus?.platform,
        ) ?? UNKNOWN,
    },
    { label: "反向 WS", value: reverseWsUrl },
    {
      label: "Bridge 检查时间",
      value: formatDateTime(bridgeHealth?.checked_at),
    },
  ]

  const cpuRows: KeyValue[] = [
    { label: "型号", value: runtime?.cpu_model ?? UNKNOWN },
    { label: "内核数", value: String(runtime?.cpu_count ?? UNKNOWN) },
    { label: "主频", value: formatFrequency(runtime?.cpu_frequency_mhz) },
    {
      label: "使用率",
      value: formatPercent(runtime?.aggregate.cpu_percent),
    },
    {
      label: "后端主进程",
      value: formatPercent(runtime?.current_process.cpu_percent),
    },
    {
      label: "线程数",
      value: String(runtime?.aggregate.thread_count ?? UNKNOWN),
    },
  ]

  const memoryRows: KeyValue[] = [
    { label: "总量", value: formatBytes(runtime?.memory_total_bytes) },
    { label: "使用量", value: formatBytes(runtime?.memory_used_bytes) },
    { label: "可用量", value: formatBytes(runtime?.memory_available_bytes) },
    {
      label: "使用率",
      value: formatPercent(runtime?.memory_percent, UNKNOWN),
    },
    { label: "后端进程", value: formatBytes(runtime?.aggregate.rss_bytes) },
    {
      label: "当前进程",
      value: formatBytes(runtime?.current_process.rss_bytes),
    },
  ]

  const networkRows: KeyValue[] = [
    { label: "HTTP服务器", value: runtime ? "1" : "0" },
    {
      label: "HTTP客户端",
      value: bridgeHealth?.backend?.reachable ? "1" : "0",
    },
    { label: "WS服务器", value: reverseWsUrl === UNKNOWN ? "0" : "1" },
    { label: "WS客户端", value: String(connectedRobotCount) },
    {
      label: "已加载机器人",
      value: String(loadedRobotCount),
    },
    {
      label: "已连接身份",
      value: String(bridgeHealth?.connected_identities?.length ?? 0),
    },
  ]

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">TermMan</Badge>
            {isAdmin ? (
              <Badge variant="secondary" className="gap-1">
                <Shield className="size-3" />
                Admin
              </Badge>
            ) : (
              <Badge variant="outline" className="gap-1">
                <User className="size-3" />
                User
              </Badge>
            )}
            <StatusPill
              connected={!bridgeHealthQuery.isError}
              label={bridgeHealthQuery.isError ? "Bridge 异常" : "Bridge 可读"}
            />
          </div>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight">
            数据看板
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            汇总后端运行时、机器人桥接、终端和 Daemon 的当前状态。
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refreshDashboard}
          disabled={
            loading ||
            runtimeQuery.isFetching ||
            bridgeHealthQuery.isFetching ||
            robotsQuery.isFetching
          }
        >
          <RefreshCw
            className={`size-4 ${
              loading ||
              runtimeQuery.isFetching ||
              bridgeHealthQuery.isFetching ||
              robotsQuery.isFetching
                ? "animate-spin"
                : ""
            }`}
          />
          刷新
        </Button>
      </section>

      {runtimeQuery.isError ? (
        <ErrorNotice
          title="后端运行时不可读"
          message={
            isAdmin
              ? runtimeQuery.error.message
              : "后端运行时指标仅管理员可见。"
          }
        />
      ) : null}
      {bridgeHealthQuery.isError ? (
        <ErrorNotice
          title="机器人桥接不可读"
          message={bridgeHealthQuery.error.message}
        />
      ) : null}
      {robotsQuery.isError ? (
        <ErrorNotice title="机器人列表不可读" message={robotsQuery.error.message} />
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          title="后端进程"
          value={String(runtime?.aggregate.process_count ?? 0)}
          hint={runtimeCpuHint}
          icon={Server}
        />
        <MetricTile
          title="CPU 使用率"
          value={formatPercent(runtime?.aggregate.cpu_percent)}
          hint={`当前进程 ${formatPercent(runtime?.current_process.cpu_percent)}`}
          icon={Cpu}
        />
        <MetricTile
          title="系统内存"
          value={formatBytes(runtime?.memory_used_bytes)}
          hint={`总量 ${formatBytes(runtime?.memory_total_bytes)} · ${formatPercent(runtime?.memory_percent, UNKNOWN)}`}
          icon={HardDrive}
        />
        <MetricTile
          title="机器人连接"
          value={`${connectedRobotCount}/${loadedRobotCount}`}
          hint={`${robots.length} 个配置 · ${bridgeHealth?.platforms?.join(", ") || "无平台"}`}
          icon={Bot}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Card className="gap-4 py-5">
          <CardHeader className="flex flex-row items-center gap-3 px-5">
            <div className="flex size-10 items-center justify-center rounded-md border bg-muted/30">
              <Server className="size-5 text-primary" />
            </div>
            <div>
              <CardTitle>系统信息</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                后端 API 和宿主环境
              </p>
            </div>
          </CardHeader>
          <CardContent className="px-5">
            <KeyValueGrid rows={systemRows} />
          </CardContent>
        </Card>

        <Card className="gap-4 py-5">
          <CardHeader className="flex flex-row items-start justify-between gap-3 px-5">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-md border bg-muted/30">
                  <Bot className="size-5 text-primary" />
                </div>
                <div className="min-w-0">
                  <CardTitle className="truncate">{robotName}</CardTitle>
                  <p className="mt-1 truncate font-mono text-sm text-muted-foreground">
                    {robotIdentity}
                  </p>
                </div>
              </div>
            </div>
            <StatusPill
              connected={Boolean(primaryRobotStatus?.connected)}
              label={primaryRobotStatus?.connected ? "已连接" : "未连接"}
            />
          </CardHeader>
          <CardContent className="px-5">
            <KeyValueGrid rows={robotRows} />
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <ResourcePanel title="CPU" icon={Gauge} rows={cpuRows} />
        <ResourcePanel title="内存" icon={Activity} rows={memoryRows} />
        <ResourcePanel title="网络配置" icon={Network} rows={networkRows} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card className="gap-4 py-5">
          <CardHeader className="flex flex-row items-center justify-between gap-3 px-5">
            <div className="flex items-center gap-2">
              <Wifi className="size-4 text-primary" />
              <CardTitle>机器人桥接</CardTitle>
            </div>
            <Badge variant="outline">
              {connectedRobotCount}/{loadedRobotCount}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-3 px-5">
            {bridgeRobotEntries.length === 0 ? (
              <Alert>
                <AlertTitle>暂无桥接状态</AlertTitle>
                <AlertDescription>
                  当前没有从 robot bridge 读取到机器人连接信息。
                </AlertDescription>
              </Alert>
            ) : (
              bridgeRobotEntries.map(([robotId, status]) => {
                const robot = robotMap.get(robotId)
                const socket = isRecord(status.onebot_socket)
                  ? status.onebot_socket
                  : {}
                return (
                  <div
                    key={robotId}
                    className="rounded-md border bg-background px-4 py-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {robot?.name || robotId}
                        </p>
                        <p className="truncate font-mono text-xs text-muted-foreground">
                          {status.identity || UNKNOWN}
                        </p>
                      </div>
                      <StatusPill
                        connected={status.connected}
                        label={status.connected ? "已连接" : "未连接"}
                      />
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                      <span>
                        Socket:{" "}
                        {readRecordValue(socket, ["event", "mode"]) ?? UNKNOWN}
                      </span>
                      <span>
                        最近事件: {formatDateTime(status.last_platform_event_at)}
                      </span>
                      <span>
                        最近消息: {formatDateTime(status.last_message_event_at)}
                      </span>
                    </div>
                    {status.error ? (
                      <p className="mt-2 break-words text-xs text-red-600 dark:text-red-300">
                        {status.error}
                      </p>
                    ) : null}
                  </div>
                )
              })
            )}
          </CardContent>
        </Card>

        <Card className="gap-4 py-5">
          <CardHeader className="flex flex-row items-center justify-between gap-3 px-5">
            <div className="flex items-center gap-2">
              <Terminal className="size-4 text-primary" />
              <CardTitle>终端与 Daemon</CardTitle>
            </div>
            <Badge variant="outline">{items.length} 终端</Badge>
          </CardHeader>
          <CardContent className="grid gap-3 px-5 sm:grid-cols-2">
            <div className="rounded-md border px-4 py-3">
              <p className="text-xs text-muted-foreground">终端</p>
              <p className="mt-1 text-xl font-semibold">
                {itemStats.running}/{itemStats.total}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                运行中 / 总数
              </p>
            </div>
            <div className="rounded-md border px-4 py-3">
              <p className="text-xs text-muted-foreground">Daemon</p>
              <p className="mt-1 text-xl font-semibold">
                {onlineDaemonCount}/{daemons.length}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">在线 / 总数</p>
            </div>
            <div className="rounded-md border px-4 py-3">
              <p className="text-xs text-muted-foreground">浏览器连接</p>
              <p className="mt-1 text-xl font-semibold">
                {itemStats.browserConnections}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">当前连接数</p>
            </div>
            <div className="rounded-md border px-4 py-3">
              <p className="text-xs text-muted-foreground">用户订阅</p>
              <p className="mt-1 text-xl font-semibold">
                {itemStats.connectedUsers}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">后端会话数</p>
            </div>
          </CardContent>
        </Card>
      </section>

      <Card className="gap-4 py-5">
        <CardHeader className="flex flex-row items-center justify-between px-5">
          <div>
            <CardTitle>{isAdmin ? "全部终端明细" : "我的终端明细"}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              仍可在这里展开终端、查看连接用户并执行原有管理操作。
            </p>
          </div>
        </CardHeader>
        <CardContent className="px-5">
          {loading ? (
            <p className="text-sm text-muted-foreground">正在加载终端...</p>
          ) : items.length === 0 ? (
            <Alert>
              <AlertTitle>暂无终端</AlertTitle>
              <AlertDescription>
                {isAdmin ? "系统中还没有终端。" : "你还没有任何终端。"}
              </AlertDescription>
            </Alert>
          ) : isAdmin ? (
            <div className="space-y-4">
              {daemons.map((daemon) => (
                <div key={daemon.id} className="rounded-md border">
                  <div
                    className="flex w-full cursor-pointer items-center justify-between p-4 text-left hover:bg-muted"
                    onClick={() => toggleDaemonExpand(daemon.id)}
                  >
                    <div className="flex min-w-0 items-center">
                      {expandedDaemons[daemon.id] ? (
                        <ChevronDown className="mr-2 size-5 shrink-0" />
                      ) : (
                        <ChevronRight className="mr-2 size-5 shrink-0" />
                      )}
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate font-medium">
                            Daemon: {daemon.id}
                          </h3>
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(
                              daemon.online ? "online" : "offline",
                            )}`}
                          >
                            {daemon.online ? "在线" : "离线"}
                          </span>
                          {!daemon.online && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 px-2"
                              onClick={(event) => {
                                event.stopPropagation()
                                handleReconnectDaemon(daemon.id)
                              }}
                            >
                              <RefreshCw className="size-3" />
                              重连
                            </Button>
                          )}
                        </div>
                        <p className="truncate text-sm text-muted-foreground">
                          URL: {daemon.url}
                        </p>
                      </div>
                    </div>
                    <div className="shrink-0 text-sm font-medium">
                      {daemon.items.length} 终端
                    </div>
                  </div>

                  {expandedDaemons[daemon.id] && (
                    <div className="border-t">
                      {daemon.items.map((item) => (
                        <ItemCard
                          key={item.id}
                          item={item}
                          expanded={expandedItems[item.id]}
                          onToggleExpand={() => toggleItemExpand(item.id)}
                          onDisconnectUser={(userUuid, userName, ip) =>
                            setDisconnectDialog({
                              open: true,
                              itemId: item.id,
                              itemTitle: item.title,
                              userUuid,
                              userName,
                              ip,
                            })
                          }
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-4">
              {items.map((item) => (
                <ItemCard
                  key={item.id}
                  item={item}
                  expanded={expandedItems[item.id]}
                  onToggleExpand={() => toggleItemExpand(item.id)}
                  onDisconnectUser={(userUuid, userName, ip) =>
                    setDisconnectDialog({
                      open: true,
                      itemId: item.id,
                      itemTitle: item.title,
                      userUuid,
                      userName,
                      ip,
                    })
                  }
                  showOwner={false}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={disconnectDialog?.open}
        onOpenChange={(open) => !open && setDisconnectDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>断开用户连接</DialogTitle>
            <DialogDescription>
              确认要把用户{" "}
              <strong>
                {disconnectDialog?.userName || disconnectDialog?.userUuid}
              </strong>{" "}
              (IP: {disconnectDialog?.ip}) 从终端{" "}
              <strong>{disconnectDialog?.itemTitle}</strong> 中断开吗？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDisconnectDialog(null)}
              disabled={disconnecting}
            >
              取消
            </Button>
            <Button
              onClick={handleDisconnectUser}
              disabled={disconnecting}
              variant="destructive"
            >
              {disconnecting ? "断开中..." : "断开"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ItemCard({
  item,
  expanded,
  onToggleExpand,
  onDisconnectUser,
  showOwner = true,
}: {
  item: Item
  expanded: boolean
  onToggleExpand: () => void
  onDisconnectUser: (userUuid: string, userName: string, ip: string) => void
  showOwner?: boolean
}) {
  const subscribers = item.subscribers ?? []
  const [handlers, setHandlers] = useState<any[]>([])
  const [loadingHandlers, setLoadingHandlers] = useState(false)

  useEffect(() => {
    const fetchHandlers = async () => {
      if (expanded && item.id) {
        setLoadingHandlers(true)
        try {
          const result =
            await ItemHandlerAssociationsService.getHandlersForItem({
              itemId: item.id,
            })
          setHandlers(result || [])
        } catch (error) {
          console.error("Failed to fetch handlers:", error)
        } finally {
          setLoadingHandlers(false)
        }
      }
    }
    fetchHandlers()
  }, [expanded, item.id])

  return (
    <div className="ml-4 border-b last:border-b-0">
      <div
        className="flex w-full cursor-pointer items-center justify-between p-4 text-left hover:bg-muted"
        onClick={onToggleExpand}
      >
        <div className="flex min-w-0 items-center">
          {expanded ? (
            <ChevronDown className="mr-2 size-5 shrink-0" />
          ) : (
            <ChevronRight className="mr-2 size-5 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/items/$itemId"
                params={{ itemId: item.id }}
                className="font-medium hover:text-blue-600 hover:underline"
                onClick={(event) => event.stopPropagation()}
              >
                {item.title}
              </Link>
              {handlers.length > 0 && (
                <Link
                  to="/item-handlers/$itemHandlerId"
                  params={{ itemHandlerId: handlers[0].id }}
                  onClick={(event) => event.stopPropagation()}
                >
                  <Badge
                    variant="outline"
                    className="cursor-pointer gap-1 text-xs hover:bg-primary/10"
                  >
                    <Plug className="size-3" />
                    {handlers[0].name}
                  </Badge>
                </Link>
              )}
            </div>
            <p className="truncate text-sm text-muted-foreground">
              {item.description || "无描述"}
            </p>
            {showOwner && (
              <p className="truncate text-xs text-muted-foreground">
                Owner: {item.owner_id}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-sm">
          <span
            className={`rounded-full px-2 py-1 text-xs ${statusBadgeClass(
              item.status,
            )}`}
          >
            {statusLabel(item.status)}
          </span>
          <span className="text-muted-foreground">
            {item.browser_count ?? 0} 连接
          </span>
        </div>
      </div>

      {expanded && (
        <div className="space-y-4 bg-muted/50 p-4">
          {handlers.length > 0 && (
            <div>
              <h5 className="mb-2 flex items-center gap-1 text-sm font-medium">
                <Plug className="size-4" />
                Managed by:
              </h5>
              <div className="flex flex-wrap gap-2">
                {handlers.map((handler) => (
                  <Link
                    key={handler.id}
                    to="/item-handlers/$itemHandlerId"
                    params={{ itemHandlerId: handler.id }}
                  >
                    <Badge
                      variant="secondary"
                      className="cursor-pointer hover:bg-primary/20"
                    >
                      {handler.name}
                    </Badge>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {loadingHandlers ? (
            <p className="text-sm text-muted-foreground">正在加载处理器...</p>
          ) : null}

          {subscribers.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              暂无用户连接到这个终端
            </p>
          ) : (
            <div className="space-y-2">
              <h5 className="text-sm font-medium">已连接用户:</h5>
              {subscribers.map((sub) => (
                <div
                  key={sub.sid}
                  className="flex items-center justify-between rounded-md border bg-background p-3"
                >
                  <div>
                    <p className="text-sm font-medium">
                      {sub.user_name || sub.user_uuid}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      IP: {sub.ip}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Joined: {new Date(sub.join_time * 1000).toLocaleString()}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 text-destructive hover:bg-destructive/10"
                    onClick={() =>
                      onDisconnectUser(sub.user_uuid, sub.user_name, sub.ip)
                    }
                  >
                    <Trash2 className="size-4" />
                    <span className="sr-only">断开用户</span>
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Dashboard
