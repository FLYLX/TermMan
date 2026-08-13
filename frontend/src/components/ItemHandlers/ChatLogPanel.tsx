import { useEffect, useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, FileText, Loader2, MessageSquare, RefreshCw, Upload } from "lucide-react"

import {
  downloadRobotConversationMemory,
  getRobotConversationMemoryQueryKey,
  getRobotsQueryKey,
  importRobotConversationMemory,
  listRobotBindings,
  listRobotConversationMemory,
  listRobots,
  readRobotConversationMemory,
  type RobotBindingRecord,
  type RobotConversationMemoryEntry,
  type RobotRecord,
} from "@/components/Robots/api"
import { useI18n } from "@/components/locale-provider"
import useCustomToast from "@/hooks/useCustomToast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-"
  }
  if (value < 1024) {
    return `${value} B`
  }

  const units = ["KB", "MB", "GB"]
  let size = value
  let unitIndex = -1
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`
}

function getConversationTypeLabel(conversationKey: string, locale: string) {
  const type = conversationKey.split(":", 1)[0]
  if (type === "private") {
    return locale === "zh" ? "\u79c1\u804a" : "Private"
  }
  if (type === "channel") {
    return locale === "zh" ? "\u9891\u9053" : "Channel"
  }
  return locale === "zh" ? "\u7fa4\u804a" : "Group"
}

function getConversationId(conversationKey: string) {
  const [, id = conversationKey] = conversationKey.split(":", 2)
  return id
}

function getRobotName(robotId: string, robotsById: Map<string, RobotRecord>) {
  return robotsById.get(robotId)?.name || robotId
}

type ChatLogRecord = {
  robot: RobotRecord
  binding: RobotBindingRecord
  entry: RobotConversationMemoryEntry
}

export function ChatLogPanel({
  itemHandlerId,
  connectedItems,
}: {
  itemHandlerId: string
  connectedItems: any[]
}) {
  const queryClient = useQueryClient()
  const { locale, localeTag } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const connectedItemIds = useMemo(
    () => new Set(connectedItems.map((item) => String(item.id))),
    [connectedItems],
  )
  const [selectedKey, setSelectedKey] = useState("")
  const [importContent, setImportContent] = useState("")
  const [appendImport, setAppendImport] = useState(true)
  const [isImporting, setIsImporting] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const copy =
    locale === "zh"
      ? {
          title: "聊天记录",
          description:
            "查看当前 TermHandler 关联终端对应机器人的群聊/私聊 .log。",
          noTerminal: "当前 TermHandler 还没有关联终端。",
          noRobot: "当前关联终端还没有绑定机器人。",
          noLog: "这些机器人还没有写入群聊或私聊 .log。",
          logList: "会话日志",
          refresh: "刷新",
          download: "下载",
          import: "导入",
          append: "追加导入",
          replace: "覆盖导入",
          importPlaceholder: "粘贴 .log 内容...",
          importRequired: "请先粘贴要导入的 .log 内容",
          imported: "聊天记录已导入",
          importFailed: "导入聊天记录失败",
          downloadFailed: "下载聊天记录失败",
          loadingLogs: "正在加载聊天记录...",
          loadingMemory: "正在读取 .log...",
          emptyMemory: "这个会话还没有聊天记录。",
          robot: "机器人",
          terminal: "终端",
          updated: "更新时间",
          size: "大小",
        }
      : {
          title: "Chat Logs",
          description:
            "View group/private .log files for robots bound to this TermHandler's terminals.",
          noTerminal: "This TermHandler has no attached terminals.",
          noRobot: "No robot is bound to the attached terminals.",
          noLog: "These robots have not written any group/private .log yet.",
          logList: "Conversation logs",
          refresh: "Refresh",
          download: "Download",
          import: "Import",
          append: "Append import",
          replace: "Replace import",
          importPlaceholder: "Paste .log content...",
          importRequired: "Paste .log content before importing",
          imported: "Chat log imported",
          importFailed: "Failed to import chat log",
          downloadFailed: "Failed to download chat log",
          loadingLogs: "Loading chat logs...",
          loadingMemory: "Reading .log...",
          emptyMemory: "This conversation has no chat log yet.",
          robot: "Robot",
          terminal: "Terminal",
          updated: "Updated",
          size: "Size",
        }

  const robotsQuery = useQuery({
    queryKey: getRobotsQueryKey(),
    queryFn: () => listRobots(),
  })
  const robots = robotsQuery.data?.data ?? []
  const robotsById = useMemo(
    () => new Map(robots.map((robot) => [robot.id, robot])),
    [robots],
  )

  const bindingQueries = useMemo(
    () =>
      robots.map((robot) => ({
        robot,
        queryKey: ["robot-bindings", robot.id] as const,
        queryFn: () => listRobotBindings(robot.id),
      })),
    [robots],
  )

  const robotBindingQueries = useQuery({
    queryKey: ["item-handler-robot-bindings", itemHandlerId, robots.map((robot) => robot.id).join(",")],
    queryFn: async () => {
      const results = await Promise.all(
        bindingQueries.map(async ({ robot, queryFn }) => ({
          robot,
          bindings: await queryFn(),
        })),
      )
      return results
    },
    enabled: robots.length > 0,
  })

  const boundRobots = useMemo(() => {
    const results = robotBindingQueries.data ?? []
    return results
      .map(({ robot, bindings }) => ({
        robot,
        bindings: bindings.filter((binding) =>
          connectedItemIds.has(binding.item_id),
        ),
      }))
      .filter((entry) => entry.bindings.length > 0)
  }, [connectedItemIds, robotBindingQueries.data])

  const memoryQueries = useQuery({
    queryKey: [
      "item-handler-chat-log-list",
      itemHandlerId,
      boundRobots.map(({ robot }) => robot.id).join(","),
    ],
    queryFn: async () => {
      const results = await Promise.all(
        boundRobots.map(async ({ robot, bindings }) => ({
          robot,
          bindings,
          memory: await listRobotConversationMemory(robot.id),
        })),
      )
      return results
    },
    enabled: boundRobots.length > 0,
  })

  const records = useMemo<ChatLogRecord[]>(() => {
    const rows: ChatLogRecord[] = []
    for (const result of memoryQueries.data ?? []) {
      const binding = result.bindings[0]
      if (!binding) {
        continue
      }
      for (const entry of result.memory.data) {
        rows.push({ robot: result.robot, binding, entry })
      }
    }
    return rows.sort((left, right) =>
      String(right.entry.updated_at ?? "").localeCompare(
        String(left.entry.updated_at ?? ""),
      ),
    )
  }, [memoryQueries.data])

  const selectedRecord = useMemo(() => {
    if (!records.length) {
      return null
    }
    return (
      records.find(
        (record) =>
          `${record.robot.id}:${record.entry.conversation_key}` === selectedKey,
      ) ?? records[0]
    )
  }, [records, selectedKey])

  useEffect(() => {
    if (!selectedRecord) {
      setSelectedKey("")
      return
    }
    const nextKey = `${selectedRecord.robot.id}:${selectedRecord.entry.conversation_key}`
    if (selectedKey !== nextKey) {
      setSelectedKey(nextKey)
    }
  }, [selectedKey, selectedRecord])

  const memoryQuery = useQuery({
    queryKey: [
      "robot-conversation-memory-content",
      selectedRecord?.robot.id,
      selectedRecord?.entry.conversation_key,
    ],
    queryFn: () =>
      readRobotConversationMemory(
        selectedRecord!.robot.id,
        selectedRecord!.entry.conversation_key,
      ),
    enabled: Boolean(selectedRecord),
  })

  const refreshLogs = async () => {
    setIsRefreshing(true)
    try {
      await queryClient.invalidateQueries({
        queryKey: ["item-handler-chat-log-list", itemHandlerId],
      })
      await Promise.all(
        boundRobots.map(({ robot }) =>
          queryClient.invalidateQueries({
            queryKey: getRobotConversationMemoryQueryKey(robot.id),
          }),
        ),
      )
      if (selectedRecord) {
        await memoryQuery.refetch()
      }
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleDownload = async () => {
    if (!selectedRecord) {
      return
    }
    setIsDownloading(true)
    try {
      await downloadRobotConversationMemory(
        selectedRecord.robot.id,
        selectedRecord.entry,
      )
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : copy.downloadFailed,
      )
    } finally {
      setIsDownloading(false)
    }
  }

  const handleImport = async () => {
    if (!selectedRecord) {
      return
    }
    const content = importContent.trim()
    if (!content) {
      showErrorToast(copy.importRequired)
      return
    }
    setIsImporting(true)
    try {
      await importRobotConversationMemory(
        selectedRecord.robot.id,
        selectedRecord.entry.conversation_key,
        {
          content: `${content}\n`,
          append: appendImport,
        },
      )
      setImportContent("")
      showSuccessToast(copy.imported)
      await refreshLogs()
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : copy.importFailed)
    } finally {
      setIsImporting(false)
    }
  }

  const isLoading =
    robotsQuery.isLoading ||
    robotBindingQueries.isLoading ||
    memoryQueries.isLoading

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <MessageSquare className="size-5 text-sky-500" />
              {copy.title}
            </CardTitle>
            <p className="text-sm text-muted-foreground">{copy.description}</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refreshLogs()}
            disabled={isRefreshing || isLoading}
          >
            {isRefreshing ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 size-4" />
            )}
            {copy.refresh}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {connectedItems.length === 0 ? (
          <div className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
            {copy.noTerminal}
          </div>
        ) : boundRobots.length === 0 && !isLoading ? (
          <div className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
            {copy.noRobot}
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {copy.loadingLogs}
          </div>
        ) : records.length === 0 ? (
          <div className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
            {copy.noLog}
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div className="rounded-lg border">
              <div className="border-b px-3 py-2 text-sm font-medium">
                {copy.logList}
              </div>
              <ScrollArea className="h-[560px]">
                <div className="space-y-1 p-2">
                  {records.map((record) => {
                    const key = `${record.robot.id}:${record.entry.conversation_key}`
                    const selected = key === selectedKey
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                          selected
                            ? "border-sky-500/40 bg-sky-500/10"
                            : "bg-background hover:bg-muted/50"
                        }`}
                        onClick={() => setSelectedKey(key)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0 font-medium text-sm">
                            <span className="truncate">
                              {getConversationTypeLabel(
                                record.entry.conversation_key,
                                locale,
                              )}{" "}
                              {getConversationId(record.entry.conversation_key)}
                            </span>
                          </div>
                          <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                            .log
                          </Badge>
                        </div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">
                          {getRobotName(record.robot.id, robotsById)} ·{" "}
                          {record.binding.item_title}
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                          <span>{formatBytes(record.entry.size_bytes)}</span>
                          <span>
                            {record.entry.updated_at
                              ? new Date(
                                  record.entry.updated_at,
                                ).toLocaleString(localeTag)
                              : "-"}
                          </span>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </ScrollArea>
            </div>

            <div className="space-y-3">
              {selectedRecord ? (
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <FileText className="size-4 text-sky-500" />
                        <span className="font-medium">
                          {selectedRecord.entry.conversation_key}
                        </span>
                        <Badge variant="outline">
                          {selectedRecord.entry.filename}
                        </Badge>
                      </div>
                      <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                        <div>
                          {copy.robot}:{" "}
                          {getRobotName(selectedRecord.robot.id, robotsById)}
                        </div>
                        <div>
                          {copy.terminal}: {selectedRecord.binding.item_title}
                        </div>
                        <div>
                          {copy.size}:{" "}
                          {formatBytes(selectedRecord.entry.size_bytes)}
                        </div>
                        <div>
                          {copy.updated}:{" "}
                          {selectedRecord.entry.updated_at
                            ? new Date(
                                selectedRecord.entry.updated_at,
                              ).toLocaleString(localeTag)
                            : "-"}
                        </div>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void handleDownload()}
                      disabled={isDownloading}
                    >
                      {isDownloading ? (
                        <Loader2 className="mr-2 size-4 animate-spin" />
                      ) : (
                        <Download className="mr-2 size-4" />
                      )}
                      {copy.download}
                    </Button>
                  </div>
                </div>
              ) : null}

              <div className="rounded-lg border">
                {memoryQuery.isLoading ? (
                  <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    {copy.loadingMemory}
                  </div>
                ) : memoryQuery.data?.memory ? (
                  <ScrollArea className="h-[360px]">
                    <pre className="whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed">
                      {memoryQuery.data.memory}
                    </pre>
                  </ScrollArea>
                ) : (
                  <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                    {copy.emptyMemory}
                  </div>
                )}
              </div>

              <div className="rounded-lg border p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-medium">{copy.import}</div>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={appendImport}
                      onChange={(event) => setAppendImport(event.target.checked)}
                    />
                    {appendImport ? copy.append : copy.replace}
                  </label>
                </div>
                <textarea
                  value={importContent}
                  onChange={(event) => setImportContent(event.target.value)}
                  placeholder={copy.importPlaceholder}
                  className="min-h-32 w-full resize-y rounded-md border bg-background px-3 py-2 font-mono text-xs"
                />
                <div className="mt-2 flex justify-end">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => void handleImport()}
                    disabled={isImporting || !selectedRecord}
                  >
                    {isImporting ? (
                      <Loader2 className="mr-2 size-4 animate-spin" />
                    ) : (
                      <Upload className="mr-2 size-4" />
                    )}
                    {copy.import}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
