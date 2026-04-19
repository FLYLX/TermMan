import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Bot,
  Cable,
  CirclePlus,
  Loader2,
  MessageSquare,
  RadioTower,
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
import useCustomToast from "@/hooks/useCustomToast"

import {
  createRobotBinding,
  deleteRobotBinding,
  getRobotBindingsQueryKey,
  getRobotPlatformsQueryKey,
  getRobotQueryKey,
  getRobotsQueryKey,
  listRobotBindings,
  listRobotPlatforms,
  type RobotBindingRecord,
  type RobotPlatformRecord,
  type RobotRecord,
  readRobot,
  updateRobotBinding,
} from "./api"

function normalizePlatformId(platform: string | null | undefined) {
  if (platform === "qq") {
    return "qq_official"
  }
  return platform ?? ""
}

function useRobotDetailCopy() {
  const { locale } = useI18n()

  return locale === "zh"
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
}

function RobotEnabledBadge({ enabled }: { enabled: boolean }) {
  const copy = useRobotDetailCopy()

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
  const copy = useRobotDetailCopy()
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
  const copy = useRobotDetailCopy()
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

export function RobotDetail({ robotId }: { robotId: string }) {
  const copy = useRobotDetailCopy()

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
                  <Cable className="size-3.5" />
                  {copy.platform}: {platform?.label ?? robot.platform}
                </Badge>
                <Badge variant="outline" className="h-6 gap-1 px-2">
                  <RadioTower className="size-3.5" />
                  {copy.provider}: {robot.provider}
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
              <AddRobotBindingDialog
                robotId={robotId}
                availableItems={availableItems}
              />
            </div>
          </div>
        </div>
      </section>

      <Card className="rounded-3xl border bg-card shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle>{copy.bindingTitle}</CardTitle>
          <CardDescription>{copy.bindingDescription}</CardDescription>
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
    </div>
  )
}
