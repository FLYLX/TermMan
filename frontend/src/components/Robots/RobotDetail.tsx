import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Bot,
  Check,
  CirclePlus,
  Copy,
  Loader2,
  MessageSquare,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { type ItemPublic, ItemsService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"

import {
  createRobotBinding,
  deleteRobotBinding,
  getRobotBindingsQueryKey,
  getRobotDebug,
  getRobotDebugQueryKey,
  getRobotPlatformsQueryKey,
  getRobotQueryKey,
  getRobotsQueryKey,
  listRobotBindings,
  listRobotPlatforms,
  type RobotBindingRecord,
  type RobotDebugEvent,
  type RobotDebugInfo,
  type RobotPlatformRecord,
  type RobotRecord,
  readRobot,
  reloadRobotBridge,
  updateRobot,
  updateRobotBinding,
} from "./api"

function normalizePlatformId(platform: string | null | undefined) {
  if (platform === "qq") {
    return "onebot_v11"
  }
  return platform ?? ""
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

function getEditableRobotCredentials(
  robot: RobotRecord,
  platform: RobotPlatformRecord | null,
): Record<string, string> {
  const credentials = getRobotCredentials(robot)
  if (!platform) {
    return credentials
  }

  return Object.fromEntries(
    platform.fields.map((field) => [
      field.key,
      field.secret ? "" : credentials[field.key] ?? "",
    ]),
  )
}

function mergeRobotCredentialsForSave(
  robot: RobotRecord,
  platform: RobotPlatformRecord | null,
  formCredentials: Record<string, string>,
): Record<string, string> {
  const existingCredentials = getRobotCredentials(robot)
  if (!platform) {
    return existingCredentials
  }

  return Object.fromEntries(
    platform.fields
      .map((field) => {
        const formValue = formCredentials[field.key]?.trim() ?? ""
        if (formValue) {
          return [field.key, formValue] as const
        }
        if (field.secret && existingCredentials[field.key]) {
          return [field.key, existingCredentials[field.key]] as const
        }
        if (!field.secret && existingCredentials[field.key]) {
          return [field.key, existingCredentials[field.key]] as const
        }
        return null
      })
      .filter((entry): entry is readonly [string, string] => entry !== null),
  )
}

function getRecordString(
  record: Record<string, unknown> | undefined,
  key: string,
) {
  const value = record?.[key]
  return typeof value === "string" && value.trim() ? value : undefined
}

function getReverseWsEndpoint(
  debug: RobotDebugInfo | undefined,
  credentials?: Record<string, string>,
) {
  const socket = debug?.bridge?.onebot_socket
  return (
    debug?.bridge?.onebot_reverse_ws_url ||
    debug?.bridge?.napcat_ws_url ||
    getRecordString(socket, "reverse_ws_url") ||
    getRecordString(socket, "ws_url") ||
    credentials?.reverse_ws_url
  )
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
    if (["robot-bridge", "backend", "localhost", "127.0.0.1", "0.0.0.0"].includes(parsed.hostname)) {
      parsed.protocol = protocol
      parsed.hostname = currentHost
      parsed.port = parsed.port || "7000"
    }
    return parsed.toString()
  } catch {
    return endpoint
  }
}

function useRobotDetailCopy() {
  const { locale } = useI18n()

  const copy =
    locale === "zh"
      ? {
          enabled: "已启用",
          disabled: "未启用",
          back: "返回机器人列表",
          notFound: "没有找到这个机器人",
          loading: "加载机器人中...",
          loadFailed: "机器人详情加载失败",
          bindingTitle: "终端绑定",
          bindingDescription:
            "把终端绑定到当前机器人，并控制聊天入口和过滤输出分发。",
          bindingEmpty: "这个机器人还没有绑定任何终端。",
          platform: "平台",
          provider: "提供方",
          totalBindings: "绑定数",
          availableTerminals: "可绑定终端",
          manageItem: "终端",
          routeKey: "当前路由",
          alias: "路由别名",
          aliasPlaceholder: "留空则自动使用终端标题",
          allowChat: "允许聊天输入",
          receiveOutput: "接收过滤输出",
          defaultTarget: "默认聊天目标",
          save: "保存",
          remove: "解绑",
          updated: "绑定配置已更新",
          removed: "绑定已删除",
          updateFailed: "更新绑定失败",
          removeFailed: "删除绑定失败",
          removeConfirm: (title: string) => `确认解除与“${title}”的绑定吗？`,
          addTrigger: "绑定终端",
          addTitle: "给机器人绑定终端",
          addDescription: "选择一个终端，并设置这个机器人如何把消息路由给它。",
          itemPlaceholder: "选择一个终端",
          addEmpty: "当前没有可绑定的终端",
          addSuccess: "机器人绑定终端成功",
          addFailed: "绑定终端失败",
          itemRequired: "请选择一个终端",
          cancel: "取消",
          bind: "绑定",
        }
      : {
          enabled: "Enabled",
          disabled: "Disabled",
          back: "Back to robots",
          notFound: "Robot not found",
          loading: "Loading robot...",
          loadFailed: "Failed to load robot detail",
          bindingTitle: "Terminal bindings",
          bindingDescription:
            "Bind terminals to this robot and control chat routing and filtered output dispatch.",
          bindingEmpty: "This robot does not have any terminal bindings yet.",
          platform: "Platform",
          provider: "Provider",
          totalBindings: "Bindings",
          availableTerminals: "Available terminals",
          manageItem: "Terminal",
          routeKey: "Route key",
          alias: "Route alias",
          aliasPlaceholder: "Leave blank to use the terminal title",
          allowChat: "Allow chat input",
          receiveOutput: "Receive filtered output",
          defaultTarget: "Default chat target",
          save: "Save",
          remove: "Unbind",
          updated: "Binding updated",
          removed: "Binding removed",
          updateFailed: "Failed to update binding",
          removeFailed: "Failed to delete binding",
          removeConfirm: (title: string) => `Remove binding for "${title}"?`,
          addTrigger: "Bind terminal",
          addTitle: "Bind terminal to robot",
          addDescription:
            "Choose a terminal and define how this robot routes messages to it.",
          itemPlaceholder: "Select a terminal",
          addEmpty: "No available terminals to bind",
          addSuccess: "Robot binding created",
          addFailed: "Failed to bind terminal",
          itemRequired: "Please select a terminal",
          cancel: "Cancel",
          bind: "Bind",
        }

  return {
    ...copy,
    debugTitle: locale === "zh" ? "调试" : "Debug",
    debugDescription:
      locale === "zh"
        ? "查看 Bridge 连接、最近收发和错误。"
        : "Inspect bridge connectivity, recent traffic, and errors.",
    reload: locale === "zh" ? "重载 Bridge" : "Reload bridge",
    reloadRequested:
      locale === "zh" ? "Bridge 重载已请求" : "Bridge reload requested",
    reloadFailed:
      locale === "zh" ? "Bridge 重载失败" : "Failed to reload bridge",
    connected: locale === "zh" ? "已连接" : "Connected",
    disconnected: locale === "zh" ? "未连接" : "Disconnected",
    recentEvents: locale === "zh" ? "最近事件" : "Recent events",
    noEvents: locale === "zh" ? "暂无调试事件" : "No debug events yet",
  }
}

function useRobotDetailUiCopy() {
  const base = useRobotDetailCopy()
  const { locale } = useI18n()

  const page =
    locale === "zh"
      ? {
          enabled: "已启用",
          disabled: "未启用",
          back: "返回机器人列表",
          notFound: "没有找到这个机器人",
          loading: "加载机器人中...",
          loadFailed: "机器人详情加载失败",
          bindingTitle: "终端绑定",
          platform: "平台",
          provider: "提供方",
          totalBindings: "绑定数",
          availableTerminals: "可绑定终端",
          manageItem: "终端",
          routeKey: "当前路由",
          alias: "路由别名",
          aliasPlaceholder: "留空则自动使用终端标题",
          allowChat: "允许聊天输入",
          receiveOutput: "接收过滤输出",
          defaultTarget: "默认聊天目标",
          save: "保存",
          remove: "解绑",
          updated: "绑定配置已更新",
          removed: "绑定已删除",
          updateFailed: "更新绑定失败",
          removeFailed: "删除绑定失败",
          removeConfirm: (title: string) => `确认解除与“${title}”的绑定吗？`,
          addTrigger: "绑定终端",
          addTitle: "给机器人绑定终端",
          addDescription: "选择一个终端，并设置机器人如何把消息路由给它。",
          itemPlaceholder: "选择一个终端",
          addEmpty: "当前没有可绑定的终端",
          addSuccess: "机器人绑定终端成功",
          addFailed: "绑定终端失败",
          itemRequired: "请选择一个终端",
          cancel: "取消",
          bind: "绑定",
          tabConnection: "连接",
          tabBindings: "绑定",
          tabDebug: "调试",
          tabSettings: "设置",
          bindingDescription: "管理这个机器人可以收发消息的终端。",
          copied: "已复制",
          copyLabel: (label: string) => `复制${label}`,
          notConfigured: "未配置",
          connectionTitle: "NapCat 反向 WebSocket",
          connectionDescription:
            "NapCat 作为客户端，主动连接这个 OneBot V11 反向 WebSocket。",
          waitingForNapCat: "等待 NapCat 连接",
          reverseEndpoint: "反向 WS 地址",
          reverseEndpointHint:
            "请在 robot/.env 中把 ROBOT_BRIDGE_URL 设置成 NapCat 能访问的地址",
          selfIdLabel: "QQ self_id",
          selfIdHint: "填写 NapCat 当前登录的 QQ 号",
          accessTokenLabel: "Access Token",
          secretLabel: "Secret",
          reverseSettingsTitle: "NapCat 配置项",
          reverseWebSocketUrl: "反向 WebSocket 地址",
          tokenLabel: "Token",
          tokenConfigured: "使用已配置的 Access Token",
          tokenEmpty: "留空",
          selfIdFallback: "NapCat 当前登录的 QQ 号",
          settingsTitle: "基础设置",
          settingsDescription: "编辑机器人名称、启用状态和 NapCat 凭据。",
          settingsUpdated: "机器人配置已更新",
          settingsUpdateFailed: "更新机器人失败",
          nameRequired: "机器人名称不能为空",
          nameLabel: "名称",
          edit: "编辑",
          credentials: "凭据",
          keepCurrentSecret: "留空则保留当前值",
          napcatMode: "OneBot V11 反向 WebSocket",
          debugTitle: "运行调试",
          debugDescription: "查看 Bridge 连接、NapCat 事件、最近收发和错误。",
          reload: "重载 Bridge",
          reloadRequested: "Bridge 重载已请求",
          reloadFailed: "Bridge 重载失败",
          connected: "已连接",
          disconnected: "未连接",
          bridgeStatus: "Bridge",
          botStatus: "Bot",
          identity: "Identity",
          bridgeUrl: "Bridge URL",
          qqBotId: "QQ Bot ID",
          napcatReverseWs: "NapCat 反向 WS",
          checked: "Checked",
          socketEvent: "Socket Event",
          reverseEndpointStatus: "反向 WS 地址",
          socketSeen: "Socket Seen",
          lastNapcatEvent: "Last NapCat Event",
          lastMessageEvent: "Last Message Event",
          recentEvents: "最近事件",
          noEvents: "暂无调试事件",
        }
      : {
          tabConnection: "Connection",
          tabBindings: "Bindings",
          tabDebug: "Debug",
          tabSettings: "Settings",
          bindingDescription:
            "Manage the terminals this robot can send messages to and receive output from.",
          copied: "Copied",
          copyLabel: (label: string) => `Copy ${label}`,
          notConfigured: "Not configured",
          connectionTitle: "NapCat reverse WebSocket",
          connectionDescription:
            "NapCat connects as a client to this OneBot V11 reverse WebSocket.",
          waitingForNapCat: "Waiting for NapCat",
          reverseEndpoint: "Reverse WS Endpoint",
          reverseEndpointHint:
            "Set robot/.env ROBOT_BRIDGE_URL to the address NapCat can reach",
          selfIdLabel: "QQ self_id",
          selfIdHint: "Set the QQ number currently logged in to NapCat",
          accessTokenLabel: "Access Token",
          secretLabel: "Secret",
          reverseSettingsTitle: "NapCat settings",
          reverseWebSocketUrl: "Reverse WebSocket URL",
          tokenLabel: "Token",
          tokenConfigured: "Use the configured Access Token",
          tokenEmpty: "Leave blank",
          selfIdFallback: "the QQ number logged in to NapCat",
          settingsTitle: "Basic settings",
          settingsDescription:
            "Edit robot name, enabled state, and NapCat credentials.",
          settingsUpdated: "Robot updated",
          settingsUpdateFailed: "Failed to update robot",
          nameRequired: "Name is required",
          nameLabel: "Name",
          edit: "Edit",
          credentials: "Credentials",
          keepCurrentSecret: "Leave blank to keep current value",
          napcatMode: "OneBot V11 reverse WebSocket",
          debugTitle: "Runtime debug",
          debugDescription:
            "Inspect bridge connectivity, NapCat events, recent traffic, and errors.",
          reload: "Reload bridge",
          reloadRequested: "Bridge reload requested",
          reloadFailed: "Failed to reload bridge",
          connected: "Connected",
          disconnected: "Disconnected",
          bridgeStatus: "Bridge",
          botStatus: "Bot",
          identity: "Identity",
          bridgeUrl: "Bridge URL",
          qqBotId: "QQ Bot ID",
          napcatReverseWs: "NapCat Reverse WS",
          checked: "Checked",
          socketEvent: "Socket Event",
          reverseEndpointStatus: "Reverse Endpoint",
          socketSeen: "Socket Seen",
          lastNapcatEvent: "Last NapCat Event",
          lastMessageEvent: "Last Message Event",
          recentEvents: "Recent events",
          noEvents: "No debug events yet",
        }

  return { ...base, ...page }
}

function RobotEnabledBadge({ enabled }: { enabled: boolean }) {
  const copy = useRobotDetailUiCopy()

  return enabled ? (
    <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
      {copy.enabled}
    </Badge>
  ) : (
    <Badge variant="secondary">{copy.disabled}</Badge>
  )
}

async function invalidateRobotQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  robotId: string,
) {
  await queryClient.invalidateQueries({
    queryKey: getRobotBindingsQueryKey(robotId),
  })
  await queryClient.invalidateQueries({ queryKey: getRobotQueryKey(robotId) })
  await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
  await queryClient.invalidateQueries({ queryKey: ["robot-bindings"] })
}

function AddRobotBindingDialog({
  robotId,
  availableItems,
}: {
  robotId: string
  availableItems: ItemPublic[]
}) {
  const copy = useRobotDetailUiCopy()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [open, setOpen] = useState(false)
  const [itemId, setItemId] = useState("")
  const [chatAlias, setChatAlias] = useState("")
  const [allowChat, setAllowChat] = useState(true)
  const [receiveFilteredOutput, setReceiveFilteredOutput] = useState(true)
  const [isDefaultTarget, setIsDefaultTarget] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  const reset = () => {
    setItemId("")
    setChatAlias("")
    setAllowChat(true)
    setReceiveFilteredOutput(true)
    setIsDefaultTarget(false)
  }

  const handleSubmit = async () => {
    if (!itemId) {
      showErrorToast(copy.itemRequired)
      return
    }

    setIsSaving(true)
    try {
      await createRobotBinding(robotId, {
        item_id: itemId,
        chat_alias: chatAlias.trim() || null,
        allow_chat: allowChat,
        receive_filtered_output: receiveFilteredOutput,
        is_default_target: allowChat ? isDefaultTarget : false,
      })
      await invalidateRobotQueries(queryClient, robotId)
      showSuccessToast(copy.addSuccess)
      setOpen(false)
      reset()
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : copy.addFailed)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          reset()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          className="h-9 rounded-xl px-3.5"
          disabled={availableItems.length === 0}
        >
          <CirclePlus className="mr-2 size-4" />
          {copy.addTrigger}
        </Button>
      </DialogTrigger>
      <DialogContent className="rounded-2xl">
        <DialogHeader>
          <DialogTitle>{copy.addTitle}</DialogTitle>
          <DialogDescription>{copy.addDescription}</DialogDescription>
        </DialogHeader>

        {availableItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed px-4 py-6 text-sm text-muted-foreground">
            {copy.addEmpty}
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label>{copy.manageItem}</Label>
              <Select value={itemId} onValueChange={setItemId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={copy.itemPlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {availableItems.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="robot-binding-alias">{copy.alias}</Label>
              <Input
                id="robot-binding-alias"
                value={chatAlias}
                onChange={(event) => setChatAlias(event.target.value)}
                placeholder={copy.aliasPlaceholder}
              />
            </div>

            <div className="grid gap-3 rounded-2xl border bg-muted/20 p-3">
              <label className="flex items-center gap-3">
                <Checkbox
                  checked={allowChat}
                  onCheckedChange={(checked) => {
                    const next = Boolean(checked)
                    setAllowChat(next)
                    if (!next) {
                      setIsDefaultTarget(false)
                    }
                  }}
                />
                <span className="text-sm">{copy.allowChat}</span>
              </label>

              <label className="flex items-center gap-3">
                <Checkbox
                  checked={receiveFilteredOutput}
                  onCheckedChange={(checked) =>
                    setReceiveFilteredOutput(Boolean(checked))
                  }
                />
                <span className="text-sm">{copy.receiveOutput}</span>
              </label>

              <label className="flex items-center gap-3">
                <Checkbox
                  checked={isDefaultTarget}
                  disabled={!allowChat}
                  onCheckedChange={(checked) =>
                    setIsDefaultTarget(Boolean(checked))
                  }
                />
                <span className="text-sm">{copy.defaultTarget}</span>
              </label>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isSaving}
          >
            {copy.cancel}
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isSaving || availableItems.length === 0}
          >
            {isSaving ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {copy.bind}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RobotBindingCard({
  robotId,
  binding,
}: {
  robotId: string
  binding: RobotBindingRecord
}) {
  const copy = useRobotDetailUiCopy()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [chatAlias, setChatAlias] = useState(binding.chat_alias ?? "")
  const [allowChat, setAllowChat] = useState(binding.allow_chat)
  const [receiveFilteredOutput, setReceiveFilteredOutput] = useState(
    binding.receive_filtered_output,
  )
  const [isDefaultTarget, setIsDefaultTarget] = useState(
    binding.is_default_target,
  )
  const [isSaving, setIsSaving] = useState(false)
  const [isRemoving, setIsRemoving] = useState(false)

  useEffect(() => {
    setChatAlias(binding.chat_alias ?? "")
    setAllowChat(binding.allow_chat)
    setReceiveFilteredOutput(binding.receive_filtered_output)
    setIsDefaultTarget(binding.is_default_target)
  }, [
    binding.allow_chat,
    binding.chat_alias,
    binding.is_default_target,
    binding.receive_filtered_output,
  ])

  const isDirty =
    chatAlias.trim() !== (binding.chat_alias ?? "") ||
    allowChat !== binding.allow_chat ||
    receiveFilteredOutput !== binding.receive_filtered_output ||
    isDefaultTarget !== binding.is_default_target

  const handleSave = async () => {
    setIsSaving(true)
    try {
      await updateRobotBinding(robotId, binding.item_id, {
        chat_alias: chatAlias.trim() || null,
        allow_chat: allowChat,
        receive_filtered_output: receiveFilteredOutput,
        is_default_target: allowChat ? isDefaultTarget : false,
      })
      await invalidateRobotQueries(queryClient, robotId)
      showSuccessToast(copy.updated)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : copy.updateFailed)
    } finally {
      setIsSaving(false)
    }
  }

  const handleRemove = async () => {
    if (!window.confirm(copy.removeConfirm(binding.item_title))) {
      return
    }

    setIsRemoving(true)
    try {
      await deleteRobotBinding(robotId, binding.item_id)
      await invalidateRobotQueries(queryClient, robotId)
      showSuccessToast(copy.removed)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : copy.removeFailed)
    } finally {
      setIsRemoving(false)
    }
  }

  return (
    <Card className="rounded-2xl border bg-card shadow-sm">
      <CardHeader className="gap-3 pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-base">
              <Link
                to="/items/$itemId"
                params={{ itemId: binding.item_id }}
                className="hover:text-primary"
              >
                {binding.item_title}
              </Link>
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2 text-xs">
              <span>{copy.routeKey}</span>
              <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">
                {binding.route_key}
              </code>
            </CardDescription>
          </div>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 rounded-lg px-3"
              onClick={() => void handleSave()}
              disabled={!isDirty || isSaving || isRemoving}
            >
              {isSaving ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Save className="size-3.5" />
              )}
              {copy.save}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="h-8 rounded-lg px-3"
              onClick={() => void handleRemove()}
              disabled={isRemoving || isSaving}
            >
              {isRemoving ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Trash2 className="size-3.5" />
              )}
              {copy.remove}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor={`binding-alias-${binding.item_id}`}>
            {copy.alias}
          </Label>
          <Input
            id={`binding-alias-${binding.item_id}`}
            value={chatAlias}
            onChange={(event) => setChatAlias(event.target.value)}
            placeholder={copy.aliasPlaceholder}
            disabled={isSaving || isRemoving}
          />
        </div>

        <div className="grid gap-3 rounded-2xl border bg-muted/20 p-3 md:grid-cols-3">
          <label className="flex items-center gap-3">
            <Checkbox
              checked={allowChat}
              disabled={isSaving || isRemoving}
              onCheckedChange={(checked) => {
                const next = Boolean(checked)
                setAllowChat(next)
                if (!next) {
                  setIsDefaultTarget(false)
                }
              }}
            />
            <span className="text-sm">{copy.allowChat}</span>
          </label>

          <label className="flex items-center gap-3">
            <Checkbox
              checked={receiveFilteredOutput}
              disabled={isSaving || isRemoving}
              onCheckedChange={(checked) =>
                setReceiveFilteredOutput(Boolean(checked))
              }
            />
            <span className="text-sm">{copy.receiveOutput}</span>
          </label>

          <label className="flex items-center gap-3">
            <Checkbox
              checked={isDefaultTarget}
              disabled={!allowChat || isSaving || isRemoving}
              onCheckedChange={(checked) =>
                setIsDefaultTarget(Boolean(checked))
              }
            />
            <span className="text-sm">{copy.defaultTarget}</span>
          </label>
        </div>
      </CardContent>
    </Card>
  )
}

function getSafePlatforms(data: unknown): RobotPlatformRecord[] {
  return Array.isArray(data) ? (data as RobotPlatformRecord[]) : []
}

function getSafeBindings(data: unknown): RobotBindingRecord[] {
  return Array.isArray(data) ? (data as RobotBindingRecord[]) : []
}

function getSafeItems(data: unknown): ItemPublic[] {
  if (
    data &&
    typeof data === "object" &&
    "data" in data &&
    Array.isArray((data as { data?: unknown }).data)
  ) {
    return (data as { data: ItemPublic[] }).data
  }
  return []
}

function getErrorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function formatDebugPayload(payload: Record<string, unknown>) {
  const entries = [
    ["platform", payload.platform],
    ["socket", payload.socket_path],
    ["client", payload.client],
    ["asgi", payload.asgi_type],
    ["username", payload.username],
    ["self_id", payload.self_id],
    ["user_id", payload.user_id],
    ["post_type", payload.post_type],
    ["meta_event_type", payload.meta_event_type],
    ["message_type", payload.message_type],
    ["sub_type", payload.sub_type],
    ["group_id", payload.group_id],
    ["message_id", payload.message_id],
    ["session", payload.session_id],
    ["shard", payload.shard],
    ["sender", payload.sender_key],
    ["target", payload.target_id],
    ["target_type", payload.target_type],
    ["item", payload.item_title ?? payload.item_id],
    ["route", payload.route_key],
    ["raw", payload.raw_message],
    ["action", payload.action],
    ["echo", payload.echo],
    ["status", payload.status],
    ["retcode", payload.retcode],
    ["interval", payload.interval],
    ["text", payload.text_preview],
    ["bytes", payload.bytes_length],
    ["code", payload.code],
    ["reason", payload.reason],
    ["retry_after", payload.retry_after_seconds],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "")

  return entries
    .map(([label, value]) => `${label}: ${String(value)}`)
    .join(" | ")
}

function getDebugDirectionLabel(event: RobotDebugEvent) {
  if (event.direction === "platform_to_bridge") {
    return "IN"
  }
  if (
    event.direction === "bridge_to_platform" ||
    event.direction === "backend_to_bridge"
  ) {
    return "OUT"
  }
  return "SYS"
}

function RobotKeyValue({
  label,
  value,
}: {
  label: string
  value?: string | null
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border bg-muted/10 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-sm">{value || "-"}</span>
    </div>
  )
}

function CopyableConfigValue({
  label,
  value,
  mutedValue,
  secret = false,
}: {
  label: string
  value?: string | null
  mutedValue?: string
  secret?: boolean
}) {
  const copyText = useRobotDetailUiCopy()
  const [copiedText, copy] = useCopyToClipboard()
  const displayValue = value || mutedValue || "-"
  const canCopy = Boolean(value)
  const isCopied = copiedText === value

  return (
    <div className="grid gap-1.5 rounded-xl border bg-muted/10 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-7 rounded-lg"
              disabled={!canCopy}
              onClick={() => {
                if (value) {
                  void copy(value)
                }
              }}
            >
              {isCopied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              <span className="sr-only">{copyText.copyLabel(label)}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {isCopied ? copyText.copied : copyText.copyLabel(label)}
          </TooltipContent>
        </Tooltip>
      </div>
      <div
        className={
          value
            ? "break-all font-mono text-sm"
            : "break-all font-mono text-sm text-muted-foreground"
        }
      >
        {secret && value ? "********" : displayValue}
      </div>
    </div>
  )
}

function RobotConnectionGuidePanel({
  robot,
  debug,
}: {
  robot: RobotRecord
  debug?: RobotDebugInfo
}) {
  const copy = useRobotDetailUiCopy()
  const credentials = getRobotCredentials(robot)
  const socket = debug?.bridge?.onebot_socket
  const reverseWsUrl = getReverseWsEndpoint(debug, credentials)
  const publicReverseWsUrl = getPublicReverseWsEndpoint(reverseWsUrl)
  const accessToken = credentials.access_token
  const secret = credentials.secret
  const selfId = credentials.self_id
  const connected = Boolean(debug?.bridge?.connected || socket?.connected)

  return (
    <Card className="rounded-3xl border bg-card shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>{copy.connectionTitle}</CardTitle>
            <CardDescription>{copy.connectionDescription}</CardDescription>
          </div>
          <Badge
            className={
              connected
                ? "w-fit border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "w-fit"
            }
            variant={connected ? "outline" : "secondary"}
          >
            {connected ? copy.connected : copy.waitingForNapCat}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-2">
          <CopyableConfigValue
            label={copy.reverseEndpoint}
            value={publicReverseWsUrl}
            mutedValue={copy.reverseEndpointHint}
          />
          <CopyableConfigValue
            label={copy.selfIdLabel}
            value={selfId}
            mutedValue={copy.selfIdHint}
          />
          <CopyableConfigValue
            label={copy.accessTokenLabel}
            value={accessToken}
            mutedValue={copy.notConfigured}
          />
          <CopyableConfigValue
            label={copy.secretLabel}
            value={secret}
            mutedValue={copy.notConfigured}
            secret
          />
        </div>

        <div className="grid gap-2 rounded-xl border bg-muted/10 p-3 text-sm text-muted-foreground">
          <div className="font-medium text-foreground">
            {copy.reverseSettingsTitle}
          </div>
          <div className="grid gap-1">
            <div>
              {copy.reverseWebSocketUrl}:{" "}
              <span className="font-mono text-foreground">
                {publicReverseWsUrl}
              </span>
            </div>
            <div>
              {copy.selfIdLabel}:{" "}
              <span className="font-mono text-foreground">
                {selfId || copy.selfIdFallback}
              </span>
            </div>
            <div>
              {copy.tokenLabel}:{" "}
              <span className="font-mono text-foreground">
                {accessToken || copy.tokenEmpty}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function RobotBasicConfigPanel({
  robot,
  platform,
}: {
  robot: RobotRecord
  platform: RobotPlatformRecord | null
}) {
  const copy = useRobotDetailUiCopy()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [isEditing, setIsEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const credentials = getRobotCredentials(robot)
  const [form, setForm] = useState(() => ({
    name: robot.name,
    is_enabled: robot.is_enabled,
    credentials: getEditableRobotCredentials(robot, platform),
  }))

  useEffect(() => {
    if (!isEditing) {
      setForm({
        name: robot.name,
        is_enabled: robot.is_enabled,
        credentials: getEditableRobotCredentials(robot, platform),
      })
    }
  }, [isEditing, platform, robot])

  const handleSave = async () => {
    if (!form.name.trim()) {
      showErrorToast(copy.nameRequired)
      return
    }

    const credentials = mergeRobotCredentialsForSave(
      robot,
      platform,
      form.credentials,
    )
    const options = { ...(robot.config?.options ?? {}) }
    delete options.route_key

    setIsSaving(true)
    try {
      await updateRobot(robot.id, {
        name: form.name.trim(),
        platform: normalizePlatformId(robot.platform),
        protocol: normalizePlatformId(robot.protocol),
        provider: robot.provider,
        is_enabled: form.is_enabled,
        use_websocket: robot.use_websocket,
        config: {
          ...(robot.config ?? {}),
          credentials,
          options,
        },
      })
      await reloadRobotBridge(robot.id)
      await queryClient.invalidateQueries({ queryKey: getRobotQueryKey(robot.id) })
      await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
      await queryClient.invalidateQueries({
        queryKey: getRobotDebugQueryKey(robot.id),
      })
      showSuccessToast(copy.settingsUpdated)
      setIsEditing(false)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : copy.settingsUpdateFailed,
      )
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Card className="rounded-3xl border bg-card shadow-sm">
      <CardHeader className="flex flex-col gap-3 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>{copy.settingsTitle}</CardTitle>
          <CardDescription>{copy.settingsDescription}</CardDescription>
        </div>
        <div className="flex gap-2">
          {isEditing ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsEditing(false)}
                disabled={isSaving}
              >
                {copy.cancel}
              </Button>
              <Button
                type="button"
                onClick={() => void handleSave()}
                disabled={isSaving}
              >
                {isSaving ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
                {copy.save}
              </Button>
            </>
          ) : (
            <Button type="button" variant="outline" onClick={() => setIsEditing(true)}>
              {copy.edit}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        {isEditing ? (
          <>
            <div className="grid gap-2">
              <Label htmlFor="robot-edit-name">{copy.nameLabel}</Label>
              <Input
                id="robot-edit-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
              />
            </div>
            <label className="flex items-center gap-3 rounded-xl border bg-muted/10 p-3">
              <Checkbox
                checked={form.is_enabled}
                onCheckedChange={(checked) =>
                  setForm((current) => ({
                    ...current,
                    is_enabled: Boolean(checked),
                  }))
                }
              />
              <span className="text-sm">{copy.enabled}</span>
            </label>
            <div className="grid gap-3">
              <div className="text-sm font-medium">{copy.credentials}</div>
              {(platform?.fields ?? []).map((field) => (
                <div key={field.key} className="grid gap-2">
                  <Label htmlFor={`robot-edit-${field.key}`}>
                    {field.label}
                    {field.required ? " *" : ""}
                  </Label>
                  <Input
                    id={`robot-edit-${field.key}`}
                    type={field.secret ? "password" : "text"}
                    value={form.credentials[field.key] ?? ""}
                    placeholder={
                      field.secret ? copy.keepCurrentSecret : undefined
                    }
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        credentials: {
                          ...current.credentials,
                          [field.key]: event.target.value,
                        },
                      }))
                    }
                  />
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <RobotKeyValue label={copy.nameLabel} value={robot.name} />
            <RobotKeyValue label="NapCat" value={copy.napcatMode} />
            <RobotKeyValue
              label={copy.selfIdLabel}
              value={credentials.self_id ?? robot.app_id}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RobotDebugPanel({
  robotId,
  debug,
}: {
  robotId: string
  debug?: RobotDebugInfo
}) {
  const copy = useRobotDetailUiCopy()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [isReloading, setIsReloading] = useState(false)
  const bridge = debug?.bridge
  const onebotSocket = bridge?.onebot_socket
  const reverseWsUrl = getReverseWsEndpoint(debug)
  const publicReverseWsUrl = getPublicReverseWsEndpoint(reverseWsUrl)

  const handleReload = async () => {
    setIsReloading(true)
    try {
      const result = await reloadRobotBridge(robotId)
      if (!result.success) {
        throw new Error(result.error || copy.reloadFailed)
      }
      showSuccessToast(copy.reloadRequested)
      await queryClient.invalidateQueries({
        queryKey: getRobotDebugQueryKey(robotId),
      })
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : copy.reloadFailed)
    } finally {
      setIsReloading(false)
    }
  }

  return (
    <Card className="rounded-3xl border bg-card shadow-sm">
      <CardHeader className="flex flex-col gap-3 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>{copy.debugTitle}</CardTitle>
          <CardDescription>{copy.debugDescription}</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-xl px-3.5"
            onClick={() => void handleReload()}
            disabled={isReloading}
          >
            {isReloading ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 size-4" />
            )}
            {copy.reload}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2 text-sm md:grid-cols-4">
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.bridgeStatus}
            </div>
            <div className="mt-1 font-medium">
              {bridge?.status ?? "unknown"}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.botStatus}
            </div>
            <div className="mt-1 font-medium">
              {bridge?.connected ? copy.connected : copy.disconnected}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.identity}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.identity ?? "-"}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.bridgeUrl}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.url ?? "-"}
            </div>
          </div>
        </div>

        <div className="grid gap-2 text-sm md:grid-cols-3">
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.qqBotId}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.bot?.bot_info?.id
                ? String(bridge.bot.bot_info.id)
                : bridge?.bot?.self_id || "-"}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.napcatReverseWs}
            </div>
            <div className="mt-1 truncate font-medium">
              {onebotSocket?.connected ? copy.connected : copy.disconnected}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.checked}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.checked_at
                ? new Date(bridge.checked_at).toLocaleString()
                : "-"}
            </div>
          </div>
        </div>

        <div className="grid gap-2 text-sm md:grid-cols-3">
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.socketEvent}
            </div>
            <div className="mt-1 truncate font-medium">
              {typeof onebotSocket?.event === "string"
                ? onebotSocket.event
                : "-"}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.reverseEndpointStatus}
            </div>
            <div className="mt-1 truncate font-medium">
              {publicReverseWsUrl}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.socketSeen}
            </div>
            <div className="mt-1 truncate font-medium">
              {typeof onebotSocket?.last_event_at === "string"
                ? new Date(onebotSocket.last_event_at).toLocaleString()
                : "-"}
            </div>
          </div>
        </div>

        <div className="grid gap-2 text-sm md:grid-cols-2">
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.lastNapcatEvent}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.last_platform_event_at
                ? new Date(bridge.last_platform_event_at).toLocaleString()
                : "-"}
            </div>
          </div>
          <div className="rounded-xl border bg-muted/10 p-3">
            <div className="text-xs text-muted-foreground">
              {copy.lastMessageEvent}
            </div>
            <div className="mt-1 truncate font-medium">
              {bridge?.last_message_event_at
                ? new Date(bridge.last_message_event_at).toLocaleString()
                : "-"}
            </div>
          </div>
        </div>

        {bridge?.error ? (
          <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {bridge.error}
          </div>
        ) : null}

        {debug?.diagnostics?.qq_event_hint ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
            {debug.diagnostics.qq_event_hint}
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="text-sm font-medium">{copy.recentEvents}</div>
          {!debug || debug.events.length === 0 ? (
            <div className="rounded-xl border border-dashed bg-muted/10 px-4 py-6 text-sm text-muted-foreground">
              {copy.noEvents}
            </div>
          ) : (
            <div className="grid gap-2">
              {debug.events.map((event, index) => (
                <div
                  key={`${event.timestamp}-${index}`}
                  className="rounded-xl border bg-muted/10 p-3 text-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary" className="h-6">
                      {getDebugDirectionLabel(event)}
                    </Badge>
                    <Badge
                      variant={
                        event.status === "error" ? "destructive" : "outline"
                      }
                      className="h-6"
                    >
                      {event.status}
                    </Badge>
                    <code className="rounded bg-background px-1.5 py-0.5">
                      {event.direction}
                    </code>
                    <span className="font-medium">{event.event}</span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(event.timestamp).toLocaleString()}
                    </span>
                  </div>
                  {event.message ? (
                    <div className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">
                      {event.message}
                    </div>
                  ) : null}
                  {formatDebugPayload(event.payload) ? (
                    <div className="mt-2 break-words font-mono text-xs text-muted-foreground">
                      {formatDebugPayload(event.payload)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function RobotDetail({ robotId }: { robotId: string }) {
  const copy = useRobotDetailUiCopy()

  const robotQuery = useQuery({
    queryKey: getRobotQueryKey(robotId),
    queryFn: () => readRobot(robotId),
    enabled: Boolean(robotId),
  })

  const bindingsQuery = useQuery({
    queryKey: getRobotBindingsQueryKey(robotId),
    queryFn: () => listRobotBindings(robotId),
    enabled: Boolean(robotId),
  })

  const itemsQuery = useQuery({
    queryKey: ["items", "robot-bindings"],
    queryFn: () => ItemsService.readItems({ skip: 0, limit: 1000 }),
  })

  const platformsQuery = useQuery({
    queryKey: getRobotPlatformsQueryKey(),
    queryFn: () => listRobotPlatforms(),
  })

  const debugQuery = useQuery({
    queryKey: getRobotDebugQueryKey(robotId),
    queryFn: () => getRobotDebug(robotId),
    enabled: Boolean(robotId),
    refetchInterval: 5000,
  })

  const robot = robotQuery.data as RobotRecord | undefined
  const bindings = useMemo(
    () => getSafeBindings(bindingsQuery.data),
    [bindingsQuery.data],
  )
  const platforms = useMemo(
    () => getSafePlatforms(platformsQuery.data),
    [platformsQuery.data],
  )
  const allItems = useMemo(
    () => getSafeItems(itemsQuery.data),
    [itemsQuery.data],
  )

  const boundItemIds = useMemo(
    () => new Set(bindings.map((binding) => binding.item_id)),
    [bindings],
  )

  const availableItems = useMemo(
    () => allItems.filter((item) => !boundItemIds.has(item.id)),
    [allItems, boundItemIds],
  )

  const platform = useMemo(() => {
    if (!robot) {
      return null
    }
    return (
      platforms.find(
        (entry) => entry.id === normalizePlatformId(robot.platform),
      ) ?? null
    )
  }, [platforms, robot])

  const isLoading = robotQuery.isLoading || bindingsQuery.isLoading
  const errorText =
    getErrorText(robotQuery.error, "") ||
    getErrorText(bindingsQuery.error, "") ||
    getErrorText(itemsQuery.error, "") ||
    getErrorText(platformsQuery.error, "")

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {copy.loading}
      </div>
    )
  }

  if (errorText) {
    return (
      <div className="py-8 text-sm text-muted-foreground">
        {copy.loadFailed}: {errorText}
      </div>
    )
  }

  if (!robot) {
    return (
      <div className="py-8 text-sm text-muted-foreground">{copy.notFound}</div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <section className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Link to="/robots" className="hover:text-foreground">
            {copy.back}
          </Link>
        </div>

        <div className="rounded-xl border bg-card/90 px-4 py-3 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                  <Bot className="size-4.5" />
                </div>
                <h1 className="break-words text-lg font-semibold tracking-tight">
                  {robot.name}
                </h1>
                <RobotEnabledBadge enabled={robot.is_enabled} />
              </div>

              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <Badge variant="outline" className="h-6 gap-1 px-2">
                  <Bot className="size-3.5" />
                  NapCat
                </Badge>
                <Badge variant="outline" className="h-6 gap-1 px-2">
                  <MessageSquare className="size-3.5" />
                  {copy.totalBindings}: {bindings.length}
                </Badge>
                <Badge variant="outline" className="h-6 gap-1 px-2">
                  <CirclePlus className="size-3.5" />
                  {copy.availableTerminals}: {availableItems.length}
                </Badge>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                asChild
                variant="outline"
                className="h-9 rounded-xl px-3.5"
              >
                <Link to="/robots">
                  <ArrowLeft className="mr-2 size-4" />
                  {copy.back}
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      <Tabs defaultValue="connection" className="gap-4">
        <TabsList className="grid h-auto w-full grid-cols-2 gap-1 rounded-xl p-1 sm:grid-cols-4 lg:w-fit">
          <TabsTrigger value="connection">{copy.tabConnection}</TabsTrigger>
          <TabsTrigger value="bindings">{copy.tabBindings}</TabsTrigger>
          <TabsTrigger value="debug">{copy.tabDebug}</TabsTrigger>
          <TabsTrigger value="settings">{copy.tabSettings}</TabsTrigger>
        </TabsList>

        <TabsContent value="connection" className="mt-0">
          <RobotConnectionGuidePanel
            robot={robot}
            debug={debugQuery.data as RobotDebugInfo | undefined}
          />
        </TabsContent>

        <TabsContent value="bindings" className="mt-0">
          <Card className="rounded-3xl border bg-card shadow-sm">
            <CardHeader className="flex flex-col gap-3 pb-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle>{copy.bindingTitle}</CardTitle>
                <CardDescription>{copy.bindingDescription}</CardDescription>
              </div>
              <AddRobotBindingDialog
                robotId={robotId}
                availableItems={availableItems}
              />
            </CardHeader>
            <CardContent>
              {bindings.length === 0 ? (
                <div className="rounded-2xl border border-dashed bg-muted/10 px-6 py-10 text-center text-sm text-muted-foreground">
                  {copy.bindingEmpty}
                </div>
              ) : (
                <div className="grid gap-3">
                  {bindings.map((binding) => (
                    <RobotBindingCard
                      key={`${binding.robot_id}:${binding.item_id}`}
                      robotId={robotId}
                      binding={binding}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="debug" className="mt-0">
          <RobotDebugPanel
            robotId={robotId}
            debug={debugQuery.data as RobotDebugInfo | undefined}
          />
        </TabsContent>

        <TabsContent value="settings" className="mt-0">
          <RobotBasicConfigPanel robot={robot} platform={platform} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
