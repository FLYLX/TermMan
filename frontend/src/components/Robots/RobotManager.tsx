import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Bot,
  Cable,
  CirclePlus,
  Copy,
  Loader2,
  Search,
  Stethoscope,
  Trash2,
  Wifi,
  WifiOff,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

import {
  type BridgeHealthResponse,
  createRobot,
  deleteRobot,
  diagnoseRobotChain,
  getBridgeHealth,
  getBridgeHealthQueryKey,
  getRobotDiagnoseQueryKey,
  getRobotPlatformsQueryKey,
  getRobotsQueryKey,
  listRobotBindings,
  listRobotPlatforms,
  listRobots,
  type RobotBindingRecord,
  type RobotDiagnoseResult,
  type RobotPlatformRecord,
  type RobotRecord,
} from "./api"

type RobotBindingsMap = Record<string, number>

type RobotFormState = {
  name: string
  credentials: Record<string, string>
}

function normalizePlatformId(platform: string | null | undefined) {
  if (platform === "qq") {
    return "onebot_v11"
  }
  return platform ?? ""
}

function buildFormForPlatform(
  platform: RobotPlatformRecord | null,
): RobotFormState {
  return {
    name: "",
    credentials: Object.fromEntries(
      (platform?.fields ?? []).map((field) => [field.key, ""]),
    ),
  }
}

function getRobotCredentials(robot: RobotRecord): Record<string, string> {
  const credentials = robot.config?.credentials
  if (credentials && typeof credentials === "object") {
    return Object.fromEntries(
      Object.entries(credentials)
        .filter(
          ([, value]) => value !== null && value !== undefined && value !== "",
        )
        .map(([key, value]) => [key, String(value)]),
    )
  }

  return {}
}

function getPublicReverseWsEndpoint(endpoint?: string | null) {
  const fallbackPath = "/onebot/v11/ws"
  if (typeof window === "undefined") {
    return endpoint || `ws://<termman-host>:7000${fallbackPath}`
  }

  const currentHost = window.location.hostname
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  const fallback = `${protocol}//${currentHost}:7000${fallbackPath}`
  if (!endpoint) {
    return fallback
  }

  try {
    const parsed = new URL(endpoint.replace(/^http:/, "ws:").replace(/^https:/, "wss:"))
    if (
      ["robot-bridge", "backend", "localhost", "127.0.0.1", "0.0.0.0"].includes(
        parsed.hostname,
      )
    ) {
      parsed.protocol = protocol
      parsed.hostname = currentHost
      parsed.port = parsed.port || "7000"
    }
    return parsed.toString()
  } catch {
    return endpoint
  }
}

function getNapCatSocketEndpoint(
  socket: RobotDiagnoseResult["chain"]["napcat_socket"],
) {
  return socket.reverse_ws_url || socket.server_url || socket.ws_url || null
}

function getConfiguredSelfId(
  identity: string | null | undefined,
  socketSelfId: string | null | undefined,
) {
  if (socketSelfId?.trim()) {
    return socketSelfId.trim()
  }
  if (!identity?.trim()) {
    return null
  }
  const [, selfId] = identity.split(":", 2)
  return selfId || identity
}

function getNapCatBridgeStatus(
  diagnoseResult: RobotDiagnoseResult,
  locale: "zh" | "en",
) {
  const qqToBridge = diagnoseResult.chain.qq_to_bridge
  const socket = diagnoseResult.chain.napcat_socket

  if (qqToBridge.connected) {
    return locale === "zh"
      ? "已接入：NapCat 登录 QQ 已匹配这个机器人"
      : "Connected: NapCat self_id matches this robot"
  }
  if (socket.connected) {
    return locale === "zh"
      ? "WS 已连接，但 self_id 没匹配这个机器人"
      : "WebSocket connected, but self_id does not match this robot"
  }
  return locale === "zh"
    ? "未接入：没有检测到这个 QQ(self_id) 的 NapCat 连接"
    : "Not connected: no NapCat connection detected for this QQ self_id"
}

function RobotStatusBadge({ enabled }: { enabled: boolean }) {
  const { t } = useI18n()

  return enabled ? (
    <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
      {t("robots.enabled")}
    </Badge>
  ) : (
    <Badge variant="secondary">{t("robots.disabled")}</Badge>
  )
}

function CreateRobotDialog({
  platforms,
}: {
  platforms: RobotPlatformRecord[]
}) {
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [open, setOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [form, setForm] = useState<RobotFormState>(() =>
    buildFormForPlatform(
      platforms.find((platform) => platform.id === "onebot_v11") ?? null,
    ),
  )

  const selectedPlatform =
    platforms.find((platform) => platform.id === "onebot_v11") ?? null

  useEffect(() => {
    if (!open || !selectedPlatform) {
      return
    }

    setForm((current) => ({
      ...current,
      credentials: Object.fromEntries(
        selectedPlatform.fields.map((field) => [
          field.key,
          current.credentials[field.key] ?? "",
        ]),
      ),
    }))
  }, [open, selectedPlatform])

  const resetForm = () => {
    setForm(buildFormForPlatform(selectedPlatform))
  }

  const handleSubmit = async () => {
    if (!selectedPlatform) {
      showErrorToast(t("robots.noPlatformsDescription"))
      return
    }
    if (!form.name.trim()) {
      showErrorToast(t("robots.nameRequired"))
      return
    }

    const missingField = selectedPlatform.fields.find(
      (field) => field.required && !form.credentials[field.key]?.trim(),
    )
    if (missingField) {
      showErrorToast(t("robots.credentialsRequired"))
      return
    }

    const credentials = Object.fromEntries(
      selectedPlatform.fields
        .map(
          (field) =>
            [field.key, form.credentials[field.key]?.trim() ?? ""] as const,
        )
        .filter(([, value]) => value !== ""),
    )

    setIsSubmitting(true)
    try {
      await createRobot({
        name: form.name.trim(),
        platform: selectedPlatform.id,
        protocol: selectedPlatform.id,
        provider: selectedPlatform.provider,
        is_enabled: true,
        use_websocket: false,
        config: {
          credentials,
          options: {},
        },
      })
      await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
      await queryClient.invalidateQueries({
        queryKey: getRobotPlatformsQueryKey(),
      })
      showSuccessToast(t("robots.createSuccess"))
      setOpen(false)
      resetForm()
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : t("robots.createFailed"),
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          resetForm()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          className="h-9 rounded-xl px-3.5"
          disabled={!selectedPlatform}
        >
          <CirclePlus className="mr-2 size-4" />
          {t("robots.add")}
        </Button>
      </DialogTrigger>
      <DialogContent className="rounded-2xl">
        <DialogHeader>
          <DialogTitle>{t("robots.addTitle")}</DialogTitle>
          <DialogDescription>{t("robots.addDescription")}</DialogDescription>
        </DialogHeader>

        {!selectedPlatform ? (
          <div className="rounded-2xl border border-dashed px-4 py-6 text-sm text-muted-foreground">
            <div className="font-medium text-foreground">
              {t("robots.noPlatforms")}
            </div>
            <div className="mt-1">{t("robots.noPlatformsDescription")}</div>
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="robot-name">{t("common.name")}</Label>
              <Input
                id="robot-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder={t("robots.namePlaceholder")}
              />
            </div>

            <div className="grid gap-2">
              <Label>{t("robots.platform")}</Label>
              <div className="rounded-xl border bg-muted/20 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">NapCat</Badge>
                  <span className="text-sm font-medium">
                    {selectedPlatform.label}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {selectedPlatform.description}
                </p>
              </div>
            </div>

            <div className="grid gap-3">
              <div className="flex gap-2 rounded-xl border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                <Cable className="mt-0.5 size-3.5 shrink-0 text-primary" />
                <span>{t("robots.serverModeHint")}</span>
              </div>
              <div className="text-sm font-medium">
                {t("robots.credentials")}
              </div>
              {(selectedPlatform?.fields ?? []).map((field) => (
                <div key={field.key} className="grid gap-2">
                  <Label htmlFor={`robot-field-${field.key}`}>
                    {field.label}
                    {field.required ? " *" : ""}
                  </Label>
                  <Input
                    id={`robot-field-${field.key}`}
                    type={field.secret ? "password" : "text"}
                    value={form.credentials[field.key] ?? ""}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        credentials: {
                          ...current.credentials,
                          [field.key]: event.target.value,
                        },
                      }))
                    }
                    placeholder={field.label}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isSubmitting}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || !selectedPlatform}
          >
            {isSubmitting ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : null}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RobotCard({
  robot,
  bindingCount,
  platformMap,
  onDelete,
  deletingRobotId,
  connectionStatus,
  reverseWsUrl,
}: {
  robot: RobotRecord
  bindingCount: number
  platformMap: Map<string, RobotPlatformRecord>
  onDelete: (robot: RobotRecord) => void
  deletingRobotId: string | null
  connectionStatus?: { identity: string; connected: boolean }
  reverseWsUrl: string
}) {
  const { locale, t } = useI18n()
  const [copiedText, copy] = useCopyToClipboard()
  const [showDiagnose, setShowDiagnose] = useState(false)
  const platform = platformMap.get(normalizePlatformId(robot.platform)) ?? null
  const credentials = getRobotCredentials(robot)
  const accessToken = credentials.access_token ?? ""
  const manageLabel = locale === "zh" ? "管理绑定" : "Manage"
  const connectedLabel = locale === "zh" ? "已连接" : "Connected"
  const disconnectedLabel = locale === "zh" ? "未连接" : "Disconnected"
  const diagnoseLabel = locale === "zh" ? "诊断" : "Diagnose"
  const wsServerLabel = locale === "zh" ? "WS 服务端地址" : "WS Server URL"
  const accessTokenLabel = "Access Token"
  const emptyTokenLabel =
    locale === "zh" ? "未配置，NapCat Token 留空" : "Not set; leave NapCat token empty"
  const copiedLabel = locale === "zh" ? "已复制" : "Copied"

  const renderNapCatConfig = (
    label: string,
    value: string,
    emptyValue: string,
  ) => {
    const hasValue = value.trim().length > 0
    const displayValue = hasValue ? value : emptyValue
    const isCopied = copiedText === value
    return (
      <div className="min-w-0 rounded-xl border bg-muted/20 px-3 py-2">
        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          <span>{label}</span>
          {hasValue ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-[11px]"
              onClick={() => void copy(value)}
              title={t("common.copyLabel", { label })}
            >
              <Copy className="size-3" />
              <span className="ml-1">{isCopied ? copiedLabel : ""}</span>
            </Button>
          ) : null}
        </div>
        <div
          className={`truncate font-mono text-[12px] ${
            hasValue ? "text-foreground" : "text-muted-foreground"
          }`}
          title={displayValue}
        >
          {displayValue}
        </div>
      </div>
    )
  }

  const {
    data: diagnoseResult,
    isLoading: isDiagnosing,
    isFetching: isDiagnosisFetching,
    isError,
    error,
    refetch: refetchDiagnose,
  } = useQuery({
    queryKey: getRobotDiagnoseQueryKey(robot.id),
    queryFn: () => diagnoseRobotChain(robot.id),
    enabled: showDiagnose,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })

  const handleDiagnose = async () => {
    if (!showDiagnose) {
      setShowDiagnose(true)
      return
    }
    await refetchDiagnose()
  }

  return (
    <div className="rounded-[22px] border bg-card p-4 shadow-sm transition-transform hover:-translate-y-0.5 hover:border-primary/25">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
            <Bot className="size-4.5" />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-semibold">
                {robot.name}
              </span>
              {connectionStatus ? (
                connectionStatus.connected ? (
                  <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 gap-1 px-1.5">
                    <Wifi className="size-3" />
                    {connectedLabel}
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="gap-1 px-1.5">
                    <WifiOff className="size-3" />
                    {disconnectedLabel}
                  </Badge>
                )
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span>{platform?.label ?? robot.platform}</span>
              <span>/</span>
              <span>{robot.provider}</span>
            </div>
            {platform?.description ? (
              <div className="line-clamp-1 text-[12px] text-muted-foreground">
                {platform.description}
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <RobotStatusBadge enabled={robot.is_enabled} />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-2.5"
            onClick={() => void handleDiagnose()}
          >
            {isDiagnosing || isDiagnosisFetching ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Stethoscope className="size-3.5" />
            )}
            <span className="ml-1">{diagnoseLabel}</span>
          </Button>
          <Button
            asChild
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-3"
          >
            <Link to="/robots/$robotId" params={{ robotId: robot.id }}>
              {manageLabel}
            </Link>
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="h-8 rounded-lg px-2.5"
            onClick={() => onDelete(robot)}
            disabled={deletingRobotId === robot.id}
          >
            {deletingRobotId === robot.id ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Trash2 className="size-3.5" />
            )}
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <div className="sm:col-span-2">
          {renderNapCatConfig(wsServerLabel, reverseWsUrl, "-")}
        </div>
        <div className="sm:col-span-2">
          {renderNapCatConfig(accessTokenLabel, accessToken, emptyTokenLabel)}
        </div>
        <div className="rounded-xl border bg-muted/20 px-3 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em]">
            <Cable className="size-3.5" />
            {t("robots.platform")}
          </div>
          <div className="truncate text-foreground">
            {platform?.label ?? robot.platform}
          </div>
        </div>

        <div className="rounded-xl border bg-muted/20 px-3 py-2">
          <div className="mb-1 text-[11px] uppercase tracking-[0.18em]">
            {t("robots.bindings")}
          </div>
          <div className="text-foreground">
            {bindingCount} {t("nav.items")}
          </div>
        </div>
      </div>

      {showDiagnose && diagnoseResult ? (
        <div className="mt-4 rounded-xl border bg-muted/10 p-3">
          <div className="mb-2 text-xs font-medium uppercase tracking-[0.15em] text-muted-foreground">
            {locale === "zh" ? "链路诊断" : "Chain Diagnosis"}
          </div>
          {diagnoseResult.checked_at ? (
            <div className="mb-2 text-[10px] text-muted-foreground">
              {locale === "zh" ? "本次诊断: " : "Checked: "}
              {new Date(diagnoseResult.checked_at).toLocaleString()}
            </div>
          ) : null}
          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-2">
              <span
                className={
                  diagnoseResult.chain.robot_config.status === "ok"
                    ? "text-emerald-600"
                    : "text-red-500"
                }
              >
                {diagnoseResult.chain.robot_config.status === "ok" ? "✓" : "✗"}
              </span>
              <span>{locale === "zh" ? "机器人配置" : "Robot Config"}</span>
              <span className="text-muted-foreground">
                {diagnoseResult.chain.robot_config.app_id || "-"}
              </span>
            </div>
            {diagnoseResult.chain.napcat_socket.status !== "not_applicable" ? (
              (() => {
                const socket = diagnoseResult.chain.napcat_socket
                const endpoint = getPublicReverseWsEndpoint(
                  getNapCatSocketEndpoint(socket),
                )
                const selfId = getConfiguredSelfId(
                  diagnoseResult.chain.qq_to_bridge.identity,
                  socket.self_id,
                )
                const connected = diagnoseResult.chain.qq_to_bridge.connected
                const statusText = getNapCatBridgeStatus(diagnoseResult, locale)
                const error =
                  diagnoseResult.chain.qq_to_bridge.error || socket.error

                return (
                  <div className="rounded-lg border bg-background px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={
                          connected ? "text-emerald-600" : "text-red-500"
                        }
                      >
                        {connected ? "✓" : "✗"}
                      </span>
                      <span className="font-medium text-foreground">
                        {locale === "zh"
                          ? "NapCat 接入 TermMan"
                          : "NapCat to TermMan"}
                      </span>
                    </div>
                    <div className="mt-2 grid gap-1 pl-5 text-[11px] text-muted-foreground">
                      <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                        <span>
                          {locale === "zh"
                            ? "机器人 QQ(self_id)"
                            : "Bot QQ (self_id)"}
                        </span>
                        <span className="font-mono text-foreground">
                          {selfId || "-"}
                        </span>
                      </div>
                      <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                        <span>
                          {locale === "zh"
                            ? "NapCat 应填地址"
                            : "NapCat server URL"}
                        </span>
                        <span className="truncate font-mono text-foreground">
                          {endpoint}
                        </span>
                      </div>
                      <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                        <span>{locale === "zh" ? "当前状态" : "Status"}</span>
                        <span className={connected ? "text-emerald-600" : ""}>
                          {statusText}
                        </span>
                      </div>
                      {error ? (
                        <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                          <span>{locale === "zh" ? "错误" : "Error"}</span>
                          <span className="break-words text-red-500">
                            {error}
                          </span>
                        </div>
                      ) : null}
                      {diagnoseResult.chain.qq_to_bridge.stale_error ? (
                        <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                          <span>
                            {locale === "zh" ? "历史错误" : "Previous error"}
                          </span>
                          <span className="break-words">
                            {diagnoseResult.chain.qq_to_bridge.stale_error}
                          </span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                )
              })()
            ) : null}
            {diagnoseResult.chain.items.map((item) => (
              <div key={item.item_id} className="flex items-center gap-2">
                <span
                  className={
                    item.daemon.online ? "text-emerald-600" : "text-red-500"
                  }
                >
                  {item.daemon.online ? "✓" : "✗"}
                </span>
                <span>
                  {locale === "zh" ? "Item → Daemon" : "Item → Daemon"}
                </span>
                <span className="text-muted-foreground truncate max-w-32">
                  {item.item_title}
                </span>
                {item.route_key ? (
                  <code className="rounded bg-background px-1 text-[10px]">
                    /term {item.route_key}
                  </code>
                ) : null}
                <span
                  className={
                    item.daemon.online ? "text-emerald-600" : "text-red-500"
                  }
                >
                  {item.daemon.status}
                </span>
              </div>
            ))}
            {diagnoseResult.chain.items.length === 0 && (
              <div className="text-muted-foreground">
                {locale === "zh" ? "没有绑定任何 Item" : "No items bound"}
              </div>
            )}
          </div>
        </div>
      ) : showDiagnose && isDiagnosing ? (
        <div className="mt-4 rounded-xl border bg-muted/10 p-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {locale === "zh" ? "正在诊断..." : "Diagnosing..."}
          </div>
        </div>
      ) : showDiagnose && isError ? (
        <div className="mt-4 rounded-xl border bg-muted/10 p-3">
          <div className="text-xs text-red-500">
            {locale === "zh" ? "诊断失败: " : "Diagnosis failed: "}
            {error instanceof Error ? error.message : String(error)}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function RobotManager() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [searchQuery, setSearchQuery] = useState("")
  const [deletingRobotId, setDeletingRobotId] = useState<string | null>(null)

  const { data: robotsData, isLoading } = useQuery({
    queryKey: getRobotsQueryKey(),
    queryFn: () => listRobots(),
  })

  const { data: platforms = [] } = useQuery({
    queryKey: getRobotPlatformsQueryKey(),
    queryFn: () => listRobotPlatforms(),
  })

  const platformMap = useMemo(
    () => new Map(platforms.map((platform) => [platform.id, platform])),
    [platforms],
  )

  const robots = robotsData?.data ?? []

  const { data: bindingCounts = {} } = useQuery<RobotBindingsMap>({
    queryKey: ["robot-bindings", robots.map((robot) => robot.id).join(",")],
    enabled: robots.length > 0,
    queryFn: async () => {
      const entries = await Promise.all(
        robots.map(async (robot) => {
          try {
            const bindings: RobotBindingRecord[] = await listRobotBindings(
              robot.id,
            )
            return [robot.id, bindings.length] as const
          } catch {
            return [robot.id, 0] as const
          }
        }),
      )
      return Object.fromEntries(entries)
    },
  })

  const { data: bridgeHealth } = useQuery<BridgeHealthResponse>({
    queryKey: getBridgeHealthQueryKey(),
    queryFn: () => getBridgeHealth(),
    refetchInterval: 30000,
    retry: false,
  })

  const connectionStatusMap = useMemo(() => {
    if (!bridgeHealth?.robots) {
      return new Map<string, { identity: string; connected: boolean }>()
    }
    return new Map(
      Object.entries(bridgeHealth.robots).map(([robotId, status]) => [
        robotId,
        status,
      ]),
    )
  }, [bridgeHealth])

  const filteredRobots = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    if (!normalizedQuery) {
      return robots
    }

    return robots.filter((robot) => {
      const platform = platformMap.get(normalizePlatformId(robot.platform))
      const credentialValues = Object.values(getRobotCredentials(robot))
      return [
        robot.name,
        robot.platform,
        robot.protocol,
        robot.provider,
        platform?.label,
        ...credentialValues,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery))
    })
  }, [platformMap, robots, searchQuery])

  const totalBindings = Object.values(bindingCounts).reduce(
    (sum, count) => sum + count,
    0,
  )
  const publicReverseWsUrl = getPublicReverseWsEndpoint(
    bridgeHealth?.onebot_reverse_ws_url,
  )

  const handleDelete = async (robot: RobotRecord) => {
    if (!window.confirm(t("robots.deleteConfirm", { name: robot.name }))) {
      return
    }

    setDeletingRobotId(robot.id)
    try {
      await deleteRobot(robot.id)
      await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
      await queryClient.invalidateQueries({ queryKey: ["robot-bindings"] })
      showSuccessToast(t("robots.deleteSuccess"))
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : t("robots.deleteFailed"),
      )
    } finally {
      setDeletingRobotId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-3xl border bg-card px-4 py-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {t("robots.pageTitle")}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("robots.pageDescription")}
            </p>
          </div>
          <CreateRobotDialog platforms={platforms} />
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            {t("robots.pageTitle")}
          </div>
          <div className="mt-2 text-2xl font-semibold">{robots.length}</div>
        </div>
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            {t("robots.bindings")}
          </div>
          <div className="mt-2 text-2xl font-semibold">{totalBindings}</div>
        </div>
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            NapCat
          </div>
          <div className="mt-2 text-2xl font-semibold">
            {bridgeHealth?.connected_bot_count ?? 0}/{robots.length}
          </div>
        </div>
      </section>

      <section className="rounded-3xl border bg-card p-4 shadow-sm">
        <div className="relative max-w-lg">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("robots.search")}
            className="h-9 rounded-xl bg-background pl-10"
          />
        </div>

        <div className="mt-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {t("common.loading")}
            </div>
          ) : filteredRobots.length === 0 ? (
            <div className="rounded-2xl border border-dashed bg-muted/10 px-6 py-10 text-center">
              <div className="mx-auto flex size-12 items-center justify-center rounded-full border bg-muted/20 text-muted-foreground">
                <Bot className="size-5" />
              </div>
              <div className="mt-4 text-sm font-medium">
                {robots.length === 0
                  ? t("robots.emptyTitle")
                  : t("table.noResults")}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {robots.length === 0
                  ? t("robots.emptyDescription")
                  : t("robots.searchEmpty")}
              </div>
            </div>
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {filteredRobots.map((robot) => (
                <RobotCard
                  key={robot.id}
                  robot={robot}
                  bindingCount={bindingCounts[robot.id] ?? 0}
                  platformMap={platformMap}
                  onDelete={handleDelete}
                  deletingRobotId={deletingRobotId}
                  connectionStatus={connectionStatusMap.get(robot.id)}
                  reverseWsUrl={publicReverseWsUrl}
                />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
