import { useQuery } from "@tanstack/react-query"
import { Activity, Clock3, Cpu, Gauge, RefreshCw, Server } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import {
  type BackendRuntimeStatsResponse,
  getBackendRuntimeStats,
} from "@/services/runtime"

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "N/A"
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

  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Sampling"
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`
}

function formatSeconds(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "N/A"
  }
  if (value < 60) {
    return `${Math.round(value)}s`
  }
  if (value < 3600) {
    return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`
  }
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  return `${hours}h ${minutes}m`
}

function formatTimestamp(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "N/A"
  }
  return new Date(value * 1000).toLocaleString()
}

function MetricCard({
  title,
  value,
  hint,
  icon: Icon,
}: {
  title: string
  value: string
  hint?: string
  icon: typeof Activity
}) {
  return (
    <Card className="border-border/70 bg-background/70">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-primary/80" />
      </CardHeader>
      <CardContent>
        <div className="text-lg font-semibold">{value}</div>
        {hint ? (
          <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ProcessCard({
  process,
  highlight = false,
}: {
  process: BackendRuntimeStatsResponse["processes"][number]
  highlight?: boolean
}) {
  return (
    <Card
      className={
        highlight ? "border-primary/45 bg-primary/5" : "border-border/70"
      }
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-sm">
              PID {process.pid}
              {highlight ? " · current" : ""}
            </CardTitle>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {process.name || process.command || "Unknown process"}
            </p>
          </div>
          <Badge variant={highlight ? "default" : "outline"}>
            {formatPercent(process.cpu_percent)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-muted-foreground">RSS</p>
          <p className="font-medium">{formatBytes(process.rss_bytes)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">VMS</p>
          <p className="font-medium">{formatBytes(process.vms_bytes)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Threads</p>
          <p className="font-medium">{process.thread_count ?? "N/A"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Open FDs</p>
          <p className="font-medium">{process.open_fds ?? "N/A"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">CPU User/System</p>
          <p className="font-medium">
            {(process.cpu_user_seconds ?? 0).toFixed(1)}s /{" "}
            {(process.cpu_system_seconds ?? 0).toFixed(1)}s
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">Uptime</p>
          <p className="font-medium">{formatSeconds(process.uptime_seconds)}</p>
        </div>
        <div className="col-span-2">
          <p className="text-muted-foreground">Started</p>
          <p className="font-medium">{formatTimestamp(process.started_at)}</p>
        </div>
        <div className="col-span-2">
          <p className="text-muted-foreground">Command</p>
          <p className="break-all font-mono text-xs">
            {process.command || "N/A"}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

export function BackendPerformance({ enabled }: { enabled: boolean }) {
  const [open, setOpen] = useState(false)
  const runtimeQuery = useQuery({
    queryKey: ["backend-runtime"],
    queryFn: getBackendRuntimeStats,
    enabled,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  })

  if (!enabled) {
    return null
  }

  const data = runtimeQuery.data
  const aggregate = data?.aggregate
  const currentProcess = data?.current_process
  const statusLabel = runtimeQuery.isError
    ? "Unavailable"
    : data
      ? `${formatBytes(aggregate?.rss_bytes)} · ${formatPercent(aggregate?.cpu_percent)}`
      : "Loading..."

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            size="lg"
            variant="outline"
            tooltip="Backend Performance"
            onClick={() => setOpen(true)}
            className="h-auto items-start gap-3 py-3"
          >
            <div className="relative mt-0.5">
              <Server className="size-4" />
              <span
                className={`absolute -right-1 -bottom-1 size-2 rounded-full ${
                  runtimeQuery.isError
                    ? "bg-red-500"
                    : runtimeQuery.isFetching
                      ? "bg-amber-400"
                      : "bg-emerald-500"
                }`}
              />
            </div>
            <div className="grid min-w-0 flex-1 text-left group-data-[collapsible=icon]:hidden">
              <span className="truncate text-sm font-medium">
                Backend Monitor
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {statusLabel}
              </span>
              {data ? (
                <span className="mt-1 truncate text-[11px] text-muted-foreground">
                  {aggregate?.process_count ?? 0} proc · pid {data.current_pid}
                </span>
              ) : null}
            </div>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-3xl">
          <SheetHeader className="border-b">
            <div className="flex items-start justify-between gap-3 pr-8">
              <div>
                <SheetTitle>Backend Performance</SheetTitle>
                <SheetDescription>
                  Live backend resource usage for the running API process group.
                </SheetDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => runtimeQuery.refetch()}
                disabled={runtimeQuery.isFetching}
              >
                <RefreshCw
                  className={`mr-2 h-4 w-4 ${
                    runtimeQuery.isFetching ? "animate-spin" : ""
                  }`}
                />
                Refresh
              </Button>
            </div>
          </SheetHeader>

          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-6 p-4">
              {runtimeQuery.isError ? (
                <Card className="border-red-500/30 bg-red-500/5">
                  <CardContent className="p-4 text-sm text-red-200">
                    Failed to load backend metrics: {runtimeQuery.error.message}
                  </CardContent>
                </Card>
              ) : null}

              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">{data?.service || "backend"}</Badge>
                <Badge variant="outline">
                  {data?.collection_scope || "current_process"}
                </Badge>
                <Badge variant="outline">
                  sampled {formatTimestamp(data?.sampled_at)}
                </Badge>
                <Badge variant="outline">host {data?.hostname || "N/A"}</Badge>
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  title="Total RSS"
                  value={formatBytes(aggregate?.rss_bytes)}
                  hint={`Python ${data?.python_version || "N/A"}`}
                  icon={Activity}
                />
                <MetricCard
                  title="CPU Usage"
                  value={formatPercent(aggregate?.cpu_percent)}
                  hint={`${(aggregate?.cpu_user_seconds ?? 0).toFixed(1)}s user / ${(aggregate?.cpu_system_seconds ?? 0).toFixed(1)}s system`}
                  icon={Cpu}
                />
                <MetricCard
                  title="Workers"
                  value={`${aggregate?.process_count ?? 0}`}
                  hint={`${aggregate?.thread_count ?? "N/A"} threads`}
                  icon={Gauge}
                />
                <MetricCard
                  title="Current PID"
                  value={`${data?.current_pid ?? "N/A"}`}
                  hint={formatSeconds(currentProcess?.uptime_seconds)}
                  icon={Clock3}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Card className="border-border/70">
                  <CardHeader>
                    <CardTitle className="text-sm">Memory Breakdown</CardTitle>
                  </CardHeader>
                  <CardContent className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-muted-foreground">RSS</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.rss_bytes)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">VMS</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.vms_bytes)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Anonymous</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.rss_anon_bytes)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">File-backed</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.rss_file_bytes)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Shared</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.rss_shmem_bytes)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Swap</p>
                      <p className="font-medium">
                        {formatBytes(aggregate?.swap_bytes)}
                      </p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/70">
                  <CardHeader>
                    <CardTitle className="text-sm">Runtime Details</CardTitle>
                  </CardHeader>
                  <CardContent className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-muted-foreground">Host</p>
                      <p className="font-medium">{data?.hostname || "N/A"}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">CPU Count</p>
                      <p className="font-medium">{data?.cpu_count ?? "N/A"}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Threads</p>
                      <p className="font-medium">
                        {aggregate?.thread_count ?? "N/A"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Open FDs</p>
                      <p className="font-medium">
                        {aggregate?.open_fds ?? "N/A"}
                      </p>
                    </div>
                    <div className="col-span-2">
                      <p className="text-muted-foreground">Platform</p>
                      <p className="break-all font-medium">
                        {data?.platform || "N/A"}
                      </p>
                    </div>
                    <div className="col-span-2">
                      <p className="text-muted-foreground">Collection Scope</p>
                      <p className="font-medium">
                        {data?.collection_scope === "parent_process_group"
                          ? "Aggregated backend master + workers"
                          : "Current process only"}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-primary" />
                  <h3 className="font-semibold">Process Details</h3>
                </div>
                <div className="grid gap-4">
                  {(data?.processes || []).map((process) => (
                    <ProcessCard
                      key={process.pid}
                      process={process}
                      highlight={process.pid === data?.current_pid}
                    />
                  ))}
                </div>
              </div>
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </>
  )
}

export default BackendPerformance
