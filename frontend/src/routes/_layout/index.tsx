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
  Plug,
  RefreshCw,
  Server,
  Shield,
  Terminal,
  Trash2,
  User,
  Wifi,
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
  getTermPawsRuntimeStats,
  getBackendRuntimeStats,
  type RuntimeServiceStats,
} from "@/services/runtime"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "TermPaws",
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

const UNKNOWN = "未上报"

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

function normalizeCpuPercent(
  value: number | null | undefined,
  cpuCount: number | null | undefined,
) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return null
  }
  const divisor = cpuCount && cpuCount > 0 ? cpuCount : 1
  return value / divisor
}

function formatCpuCores(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return UNKNOWN
  }
  const cores = value / 100
  return `${cores.toFixed(cores >= 10 ? 1 : 2)} 核`
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

function serviceIcon(kind: string) {
  if (kind === "daemon") {
    return Terminal
  }
  if (kind === "robot") {
    return Bot
  }
  return Server
}

function ServiceRuntimePanel({ services }: { services: RuntimeServiceStats[] }) {
  // robot bridge is embedded in the backend process; its stats duplicate backend's
  const visibleServices = services.filter((service) => service.service !== "robot")
  const hostLabel = (service: RuntimeServiceStats) =>
    service.runtime?.hostname || service.url || "未知节点"
  const serviceIpAddresses = (service: RuntimeServiceStats) =>
    service.runtime?.ip_addresses?.filter(Boolean) ?? []
  const serviceLocation = (service: RuntimeServiceStats) => {
    const ipAddresses = serviceIpAddresses(service)
    const parts = []
    if (ipAddresses.length > 0) {
      parts.push(`IP: ${ipAddresses.join(", ")}`)
    }
    parts.push(`主机: ${hostLabel(service)}`)
    return parts.join(" · ")
  }

  const serviceLine = (service: RuntimeServiceStats) => {
    const Icon = serviceIcon(service.kind)
    const aggregate = service.runtime?.aggregate
    return (
      <div
        key={`${service.kind}:${service.service}:${service.url ?? ""}`}
        className="relative flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2"
      >
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="size-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{service.label}</p>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{formatBytes(aggregate?.rss_bytes)}</span>
              <span>{aggregate?.process_count ?? 0} 进程</span>
              <span className="min-w-0 break-words">
                {serviceLocation(service)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-sm font-medium tabular-nums">
            {formatPercent(
              normalizeCpuPercent(aggregate?.cpu_percent, service.runtime?.cpu_count),
            )}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(
              service.status === "ok" ? "connected" : "error",
            )}`}
          >
            {service.status === "ok" ? "正常" : "异常"}
          </span>
        </div>
      </div>
    )
  }

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row items-center justify-between gap-3 px-5">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-primary" />
          <CardTitle>TermPaws 资源占用</CardTitle>
        </div>
        <Badge variant="outline">{visibleServices.length} 服务</Badge>
      </CardHeader>
      <CardContent className="px-5">
        {visibleServices.length === 0 ? (
          <Alert>
            <AlertTitle>暂无服务指标</AlertTitle>
            <AlertDescription>
              当前还没有读取到 backend 或 daemon 的运行时数据。
            </AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-2">{visibleServices.map(serviceLine)}</div>
        )}
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

type StripStat = {
  label: string
  value: string
  detail?: string
  percent?: number | null
  icon: typeof Cpu
}

function StatStrip({ stats }: { stats: StripStat[] }) {
  return (
    <Card className="gap-0 py-3 [animation:card-in_.3s_ease-out]">
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-3 px-5 sm:grid-cols-3 xl:grid-cols-6">
        {stats.map((stat) => {
          const Icon = stat.icon
          return (
            <div key={stat.label} className="flex min-w-0 flex-col gap-1">
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Icon className="size-3.5 shrink-0" />
                {stat.label}
              </span>
              <span className="truncate text-lg font-bold tabular-nums leading-tight">
                {stat.value}
              </span>
              {stat.percent != null ? (
                <div className="h-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-1 rounded-full bg-foreground/60 transition-[width] duration-500"
                    style={{
                      width: `${Math.min(Math.max(stat.percent ?? 0, 0), 100)}%`,
                    }}
                  />
                </div>
              ) : null}
              {stat.detail ? (
                <span className="truncate text-[10px] text-muted-foreground">
                  {stat.detail}
                </span>
              ) : null}
            </div>
          )
        })}
      </CardContent>
    </Card>
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
  const [detailsOpen, setDetailsOpen] = useState(false)

  const isAdmin = currentUser?.is_superuser ?? false

  const runtimeQuery = useQuery({
    queryKey: ["dashboard-backend-runtime"],
    queryFn: getBackendRuntimeStats,
    enabled: isAdmin,
    refetchInterval: 5000,
    retry: false,
  })

  const TermPawsRuntimeQuery = useQuery({
    queryKey: ["dashboard-TermPaws-runtime"],
    queryFn: getTermPawsRuntimeStats,
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
      TermPawsRuntimeQuery.refetch(),
      bridgeHealthQuery.refetch(),
      robotsQuery.refetch(),
    ])
  }

  const runtime = runtimeQuery.data as BackendRuntimeStatsResponse | undefined
  const TermPawsRuntime = TermPawsRuntimeQuery.data
  const bridgeHealth = bridgeHealthQuery.data as ExtendedBridgeHealth | undefined
  const robots = robotsQuery.data?.data ?? []
  const daemons = useMemo(() => groupItemsByDaemon(items), [items])

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

  const loadedRobotCount = bridgeHealth?.loaded_robot_count ?? robots.length
  const connectedRobotCount = Math.min(
    loadedRobotCount || Number.POSITIVE_INFINITY,
    Math.max(
      bridgeHealth?.connected_bot_count ?? 0,
      bridgeRobotEntries.filter(([, status]) => status.connected).length,
    ),
  )
  const onebotClientCount = bridgeHealth?.onebot_client_count ?? 0
  const onlineDaemonCount = daemons.filter((daemon) => daemon.online).length

  const robotConnectionValue =
    loadedRobotCount <= 0
      ? "未配置机器人"
      : connectedRobotCount > 0
        ? `${connectedRobotCount}/${loadedRobotCount} 已接入`
        : "未接入"
  const robotConnectionHint =
    loadedRobotCount <= 0
      ? `${onebotClientCount} 个 QQ 接入端`
      : `机器人 ${connectedRobotCount}/${loadedRobotCount} · QQ 接入 ${onebotClientCount}`

  return (
    <div className="space-y-3">
      <section className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">TermPaws</Badge>
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
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refreshDashboard}
          disabled={
            loading ||
            runtimeQuery.isFetching ||
            TermPawsRuntimeQuery.isFetching ||
            bridgeHealthQuery.isFetching ||
            robotsQuery.isFetching
          }
        >
          <RefreshCw
            className={`size-4 ${
              loading ||
              runtimeQuery.isFetching ||
              TermPawsRuntimeQuery.isFetching ||
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
      {TermPawsRuntimeQuery.isError ? (
        <ErrorNotice
          title="TermPaws 资源占用不可读"
          message={TermPawsRuntimeQuery.error.message}
        />
      ) : null}
      {robotsQuery.isError ? (
        <ErrorNotice title="机器人列表不可读" message={robotsQuery.error.message} />
      ) : null}

      <StatStrip
        stats={[
          {
            label: "后端 CPU",
            value: formatPercent(
              normalizeCpuPercent(runtime?.aggregate.cpu_percent, runtime?.cpu_count),
            ),
            detail: `${formatCpuCores(runtime?.aggregate.cpu_percent)} · ${runtime?.cpu_count ?? UNKNOWN} 核`,
            percent: normalizeCpuPercent(runtime?.aggregate.cpu_percent, runtime?.cpu_count),
            icon: Cpu,
          },
          {
            label: "系统内存",
            value: formatPercent(runtime?.memory_percent),
            detail: `${formatBytes(runtime?.memory_used_bytes)} / ${formatBytes(runtime?.memory_total_bytes)}`,
            percent: runtime?.memory_percent,
            icon: Gauge,
          },
          {
            label: "终端",
            value: `${itemStats.running}/${itemStats.total}`,
            detail: itemStats.error > 0 ? `${itemStats.error} 个错误` : "运行中/总数",
            icon: Terminal,
          },
          {
            label: "Daemon",
            value: `${onlineDaemonCount}/${daemons.length}`,
            detail: "在线/总数",
            icon: Plug,
          },
          {
            label: "机器人",
            value: robotConnectionValue,
            detail: robotConnectionHint,
            icon: Bot,
          },
          {
            label: "浏览器",
            value: `${itemStats.browserConnections}`,
            detail: "连接数",
            icon: Wifi,
          },
        ]}
      />

      <ServiceRuntimePanel services={TermPawsRuntime?.services ?? []} />

      <Card className="gap-3 py-3">
        <CardHeader
          className="flex cursor-pointer select-none flex-row items-center justify-between px-5 py-0"
          onClick={() => setDetailsOpen((open) => !open)}
        >
          <div>
            <CardTitle>{isAdmin ? "全部终端明细" : "我的终端明细"}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {detailsOpen
                ? "点击标题收起明细。"
                : "点击标题展开终端、查看连接用户并执行管理操作。"}
            </p>
          </div>
          {detailsOpen ? (
            <ChevronDown className="size-5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-5 shrink-0 text-muted-foreground" />
          )}
        </CardHeader>
        {detailsOpen ? (
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
        ) : null}
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
              <span className="font-medium">{item.title}</span>
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
