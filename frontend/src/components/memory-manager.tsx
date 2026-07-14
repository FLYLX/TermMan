import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  Brain,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  Filter,
  Loader2,
  Minimize2,
  Package,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { type ChangeEvent, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import {
  type InstalledSoftwareItem,
  type InstalledSoftwareUpsertRequest,
  type ManagedMemoryStatus,
  MEMORY_STATUS_COLORS,
  MEMORY_STATUS_LABELS,
  MEMORY_TYPE_COLORS,
  MEMORY_TYPE_LABELS,
  type Memory,
  type MemoryImportRequest,
  MemoryService,
  type MemoryType,
} from "@/services/memory"

interface MemoryManagerProps {
  itemId: string
}

type InstalledSoftwareForm = {
  name: string
  manager: string
  version: string
  command: string
  notes: string
}

const EMPTY_INSTALLED_SOFTWARE_FORM: InstalledSoftwareForm = {
  name: "",
  manager: "",
  version: "",
  command: "",
  notes: "",
}

function buildInstalledSoftwareForm(
  item?: InstalledSoftwareItem | null,
): InstalledSoftwareForm {
  if (!item) {
    return { ...EMPTY_INSTALLED_SOFTWARE_FORM }
  }
  return {
    name: item.name || "",
    manager: item.manager || "",
    version: item.version || "",
    command: item.command || "",
    notes: item.notes || "",
  }
}

function buildInstalledSoftwarePayload(
  form: InstalledSoftwareForm,
): InstalledSoftwareUpsertRequest {
  return {
    name: form.name.trim(),
    manager: form.manager.trim() || "manual",
    version: form.version.trim() || undefined,
    command: form.command.trim() || undefined,
    notes: form.notes.trim() || undefined,
  }
}

function getInstalledSoftwareKey(item: InstalledSoftwareItem | null) {
  if (!item) {
    return ""
  }
  return `${item.name.toLowerCase()}\u0000${(item.manager || "unknown").toLowerCase()}`
}

const MEMORY_PAGE_SIZE = 10

function buildMemoryImportRequest(payload: unknown): MemoryImportRequest {
  const source = Array.isArray(payload) ? { memories: payload } : payload
  if (!source || typeof source !== "object") {
    throw new Error("invalid memory import payload")
  }

  const record = source as { version?: unknown; memories?: unknown }
  if (!Array.isArray(record.memories)) {
    throw new Error("memory import payload missing memories")
  }

  return {
    version: typeof record.version === "number" ? record.version : undefined,
    memories: record.memories.map((entry, index) => {
      if (!entry || typeof entry !== "object") {
        throw new Error(`invalid memory at index ${index}`)
      }
      const memory = entry as Record<string, unknown>
      if (typeof memory.content !== "string" || !memory.content.trim()) {
        throw new Error(`invalid memory content at index ${index}`)
      }

      return {
        id: typeof memory.id === "string" ? memory.id : undefined,
        content: memory.content,
        metadata:
          memory.metadata &&
          typeof memory.metadata === "object" &&
          !Array.isArray(memory.metadata)
            ? (memory.metadata as Record<string, unknown>)
            : {},
      }
    }),
  }
}

export function MemoryManager({ itemId }: MemoryManagerProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [searchQuery, setSearchQuery] = useState("")
  const [filterType, setFilterType] = useState<MemoryType | "all">("all")
  const [filterStatus, setFilterStatus] = useState<ManagedMemoryStatus | "all">(
    "all",
  )
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [editingMemory, setEditingMemory] = useState<Memory | null>(null)
  const [newMemoryContent, setNewMemoryContent] = useState("")
  const [newMemoryType, setNewMemoryType] = useState<MemoryType>("fact")
  const [newMemoryTtl, setNewMemoryTtl] = useState(30)
  const [isMemoryListOpen, setIsMemoryListOpen] = useState(true)
  const importInputRef = useRef<HTMLInputElement | null>(null)
  const [isInstalledDialogOpen, setIsInstalledDialogOpen] = useState(false)
  const [editingInstalledSoftware, setEditingInstalledSoftware] =
    useState<InstalledSoftwareItem | null>(null)
  const [installedSoftwareForm, setInstalledSoftwareForm] =
    useState<InstalledSoftwareForm>(EMPTY_INSTALLED_SOFTWARE_FORM)
  const installedSoftwareQuery = useQuery({
    queryKey: ["installed-software", itemId],
    queryFn: () => MemoryService.getInstalledSoftware(itemId),
  })
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["memory-stats", itemId],
    queryFn: () => MemoryService.getMemoryStats(itemId),
  })

  const {
    data: memoriesData,
    isLoading: memoriesLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["memories", itemId, filterType, filterStatus],
    queryFn: ({ pageParam }) =>
      MemoryService.getAllMemories(
        itemId,
        filterType === "all" ? undefined : filterType,
        {
          offset: pageParam,
          limit: MEMORY_PAGE_SIZE,
          status: filterStatus === "all" ? undefined : filterStatus,
        },
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more
        ? lastPage.offset + lastPage.memories.length
        : undefined,
    enabled: isMemoryListOpen,
  })

  const {
    data: searchResults,
    refetch: performSearch,
    isLoading: searchLoading,
  } = useQuery({
    queryKey: ["memory-search", itemId, searchQuery],
    queryFn: () =>
      MemoryService.searchMemories(itemId, {
        query: searchQuery,
        n_results: 10,
      }),
    enabled: false,
  })

  const refreshInstalledSoftware = () => {
    queryClient.invalidateQueries({ queryKey: ["installed-software", itemId] })
  }

  const saveInstalledSoftwareMutation = useMutation({
    mutationFn: async () => {
      const payload = buildInstalledSoftwarePayload(installedSoftwareForm)
      if (!payload.name) {
        throw new Error("请输入软件名称")
      }
      const currentKey = getInstalledSoftwareKey(editingInstalledSoftware)
      const nextKey = `${payload.name.toLowerCase()}\u0000${(payload.manager || "manual").toLowerCase()}`
      if (editingInstalledSoftware && currentKey !== nextKey) {
        await MemoryService.deleteInstalledSoftware(itemId, {
          name: editingInstalledSoftware.name,
          manager: editingInstalledSoftware.manager,
          reason: "manual edit",
        })
      }
      return MemoryService.saveInstalledSoftware(itemId, payload)
    },
    onSuccess: () => {
      showSuccessToast("已安装列表已更新")
      setIsInstalledDialogOpen(false)
      setEditingInstalledSoftware(null)
      setInstalledSoftwareForm({ ...EMPTY_INSTALLED_SOFTWARE_FORM })
      refreshInstalledSoftware()
    },
    onError: (error) =>
      showErrorToast(
        error instanceof Error ? error.message : "更新已安装列表失败",
      ),
  })

  const deleteInstalledSoftwareMutation = useMutation({
    mutationFn: (item: InstalledSoftwareItem) =>
      MemoryService.deleteInstalledSoftware(itemId, {
        name: item.name,
        manager: item.manager,
        reason: "manual delete",
      }),
    onSuccess: () => {
      showSuccessToast("已安装记录已删除")
      refreshInstalledSoftware()
    },
    onError: () => showErrorToast("删除已安装记录失败"),
  })
  const refreshMemoryViews = () => {
    queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
    queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    if (searchQuery.trim()) {
      void performSearch()
    }
  }

  const addMemoryMutation = useMutation({
    mutationFn: () =>
      MemoryService.addMemory(itemId, {
        content: newMemoryContent,
        memory_type: newMemoryType,
        ttl_days: newMemoryTtl,
      }),
    onSuccess: (result) => {
      if (result.memory_id) {
        showSuccessToast("记忆已添加")
      } else {
        showErrorToast(result.message || "记忆保存失败")
      }
      setIsAddDialogOpen(false)
      setNewMemoryContent("")
      setNewMemoryType("fact")
      refreshMemoryViews()
    },
    onError: () => showErrorToast("添加记忆失败"),
  })

  const updateMemoryMutation = useMutation({
    mutationFn: () =>
      MemoryService.updateMemory(itemId, editingMemory!.id, {
        content: newMemoryContent,
      }),
    onSuccess: () => {
      showSuccessToast("记忆已更新")
      setIsEditDialogOpen(false)
      setEditingMemory(null)
      refreshMemoryViews()
    },
    onError: () => showErrorToast("更新记忆失败"),
  })

  const deleteMemoryMutation = useMutation({
    mutationFn: (memoryId: string) =>
      MemoryService.deleteMemory(itemId, memoryId),
    onSuccess: () => {
      showSuccessToast("记忆已删除")
      refreshMemoryViews()
    },
    onError: () => showErrorToast("删除记忆失败"),
  })

  const updateMemoryStatusMutation = useMutation({
    mutationFn: ({
      memoryId,
      status,
    }: {
      memoryId: string
      status: ManagedMemoryStatus
    }) => MemoryService.updateMemoryStatus(itemId, memoryId, { status }),
    onSuccess: (_result, variables) => {
      showSuccessToast(
        variables.status === "active"
          ? "记忆已恢复为活跃状态"
          : "记忆状态已更新",
      )
      refreshMemoryViews()
    },
    onError: () => showErrorToast("更新记忆状态失败"),
  })

  const clearMemoriesMutation = useMutation({
    mutationFn: () => MemoryService.clearMemories(itemId),
    onSuccess: () => {
      showSuccessToast("所有记忆已清除")
      refreshMemoryViews()
    },
    onError: () => showErrorToast("清除记忆失败"),
  })

  const expireMutation = useMutation({
    mutationFn: () => MemoryService.expireMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(`已清理 ${result.count} 条过期记忆`)
      refreshMemoryViews()
    },
    onError: () => showErrorToast("清理过期记忆失败"),
  })

  const dedupMutation = useMutation({
    mutationFn: () => MemoryService.deduplicateMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(`已去重 ${result.count} 条记忆`)
      refreshMemoryViews()
    },
    onError: () => showErrorToast("去重失败"),
  })

  const summarizeMutation = useMutation({
    mutationFn: () => MemoryService.summarizeMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(result.message)
      refreshMemoryViews()
    },
    onError: () => showErrorToast("压缩记忆失败"),
  })

  const exportMemoriesMutation = useMutation({
    mutationFn: () => MemoryService.exportMemories(itemId),
    onSuccess: (payload) => {
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      const timestamp = new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[:T]/g, "-")
      link.href = url
      link.download = `termman-memory-${itemId}-${timestamp}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => window.URL.revokeObjectURL(url), 0)
      showSuccessToast(`已导出 ${payload.count} 条记忆`)
    },
    onError: () => showErrorToast("导出记忆失败"),
  })

  const importMemoriesMutation = useMutation({
    mutationFn: (request: MemoryImportRequest) =>
      MemoryService.importMemories(itemId, request),
    onSuccess: (result) => {
      showSuccessToast(
        `已导入 ${result.imported} 条，跳过 ${result.skipped} 条`,
      )
      refreshMemoryViews()
    },
    onError: () => showErrorToast("导入记忆失败"),
  })

  const handleAddInstalledSoftware = () => {
    setEditingInstalledSoftware(null)
    setInstalledSoftwareForm({ ...EMPTY_INSTALLED_SOFTWARE_FORM })
    setIsInstalledDialogOpen(true)
  }

  const handleEditInstalledSoftware = (item: InstalledSoftwareItem) => {
    setEditingInstalledSoftware(item)
    setInstalledSoftwareForm(buildInstalledSoftwareForm(item))
    setIsInstalledDialogOpen(true)
  }

  const handleSaveInstalledSoftware = () => {
    if (!installedSoftwareForm.name.trim()) {
      showErrorToast("请输入软件名称")
      return
    }
    saveInstalledSoftwareMutation.mutate()
  }
  const handleSearch = () => {
    if (searchQuery.trim()) {
      performSearch()
    }
  }

  const handleImportMemoryFile = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file) {
      return
    }

    try {
      const payload = buildMemoryImportRequest(JSON.parse(await file.text()))
      importMemoriesMutation.mutate(payload)
    } catch {
      showErrorToast("导入文件格式不对")
    } finally {
      input.value = ""
    }
  }

  const handleAddMemory = () => {
    if (!newMemoryContent.trim()) {
      showErrorToast("请输入记忆内容")
      return
    }
    addMemoryMutation.mutate()
  }

  const handleEditMemory = (memory: Memory) => {
    setEditingMemory(memory)
    setNewMemoryContent(memory.content)
    setNewMemoryType(memory.metadata.memory_type)
    setIsEditDialogOpen(true)
  }

  const handleUpdateMemory = () => {
    if (!newMemoryContent.trim()) {
      showErrorToast("请输入记忆内容")
      return
    }
    updateMemoryMutation.mutate()
  }

  const getStatusAction = (memory: Memory) => {
    if (memory.metadata.memory_type === "task") {
      if (memory.metadata.status === "completed") {
        return {
          label: "恢复",
          status: "active" as ManagedMemoryStatus,
          icon: RotateCcw,
        }
      }
      return {
        label: "完成",
        status: "completed" as ManagedMemoryStatus,
        icon: CheckCircle2,
      }
    }

    if (memory.metadata.memory_type === "error") {
      if (memory.metadata.status === "resolved") {
        return {
          label: "恢复",
          status: "active" as ManagedMemoryStatus,
          icon: RotateCcw,
        }
      }
      return {
        label: "解决",
        status: "resolved" as ManagedMemoryStatus,
        icon: CheckCircle2,
      }
    }

    return null
  }

  const baseMemories =
    searchQuery.trim() && searchResults
      ? searchResults.memories
      : memoriesData?.pages.flatMap((page) => page.memories) || []
  const displayedMemories =
    searchQuery.trim() && searchResults && filterStatus !== "all"
      ? baseMemories.filter((memory) => memory.metadata.status === filterStatus)
      : baseMemories
  const totalMemoryCount =
    searchQuery.trim() && searchResults
      ? displayedMemories.length
      : (memoriesData?.pages[0]?.count ?? 0)
  const loadedMemoryCount = displayedMemories.length
  const clearableMemoryCount = stats?.total ?? totalMemoryCount
  const visibleTotalMemoryCount = totalMemoryCount || clearableMemoryCount

  return (
    <div className="space-y-4">
      <input
        ref={importInputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={handleImportMemoryFile}
      />
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Package className="size-5" />
              已安装软件
            </CardTitle>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => refreshInstalledSoftware()}
                disabled={installedSoftwareQuery.isFetching}
              >
                {installedSoftwareQuery.isFetching ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                刷新
              </Button>
              <Button size="sm" onClick={handleAddInstalledSoftware}>
                <Plus className="size-4" />
                添加软件
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {installedSoftwareQuery.isLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : (installedSoftwareQuery.data?.items.length ?? 0) === 0 ? (
            <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
              暂无已安装软件记录。agent 确认安装成功后会写入，也可以手动添加。
            </div>
          ) : (
            <div className="space-y-2">
              {installedSoftwareQuery.data?.items.map((item) => (
                <div
                  key={`${item.manager}:${item.name}`}
                  className="grid gap-3 rounded-lg border bg-muted/20 p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">{item.name}</span>
                      <Badge variant="secondary">
                        {item.manager || "unknown"}
                      </Badge>
                      {item.version ? (
                        <Badge variant="outline" className="font-mono">
                          {item.version}
                        </Badge>
                      ) : null}
                    </div>
                    {item.command ? (
                      <p className="truncate font-mono text-xs text-muted-foreground">
                        {item.command}
                      </p>
                    ) : null}
                    {item.notes ? (
                      <p className="text-xs text-muted-foreground">
                        {item.notes}
                      </p>
                    ) : null}
                    <p className="text-[11px] text-muted-foreground">
                      更新:{" "}
                      {item.updated_at
                        ? new Date(item.updated_at).toLocaleString()
                        : "-"}
                    </p>
                  </div>
                  <div className="flex justify-end gap-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8"
                      onClick={() => handleEditInstalledSoftware(item)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8 text-red-500 hover:text-red-400"
                      onClick={() => {
                        if (confirm(`删除已安装记录 ${item.name}？`)) {
                          deleteInstalledSoftwareMutation.mutate(item)
                        }
                      }}
                      disabled={deleteInstalledSoftwareMutation.isPending}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Brain className="size-5" />
            记忆统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          {statsLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : stats ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold">{stats.total}</div>
                <div className="text-sm text-zinc-400">总记忆数</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-red-400">
                  {stats.expired_count}
                </div>
                <div className="text-sm text-zinc-400">已过期</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-emerald-400">
                  {stats.status_counts.task.active}
                </div>
                <div className="text-sm text-zinc-400">进行中任务</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-zinc-200">
                  {stats.status_counts.task.completed}
                </div>
                <div className="text-sm text-zinc-400">已完成任务</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-orange-300">
                  {stats.status_counts.error.active}
                </div>
                <div className="text-sm text-zinc-400">未解决错误</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-sky-300">
                  {stats.status_counts.error.resolved}
                </div>
                <div className="text-sm text-zinc-400">已解决错误</div>
              </div>
              <div className="col-span-2 rounded-lg bg-zinc-800 p-3 md:col-span-3 xl:col-span-6">
                <div className="mb-2 text-sm text-zinc-400">按类型分布</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(stats.by_type).map(([type, count]) => (
                    <Badge key={type} variant="secondary" className="gap-1">
                      <span
                        className={`size-2 rounded-full ${MEMORY_TYPE_COLORS[type as MemoryType]}`}
                      />
                      {MEMORY_TYPE_LABELS[type as MemoryType]}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Brain className="size-5" />
              记忆管理
            </CardTitle>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsMemoryListOpen((current) => !current)}
              >
                {isMemoryListOpen ? "收起列表" : "展开列表"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exportMemoriesMutation.mutate()}
                disabled={
                  exportMemoriesMutation.isPending || clearableMemoryCount === 0
                }
              >
                {exportMemoriesMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Download className="size-4" />
                )}
                导出
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => importInputRef.current?.click()}
                disabled={importMemoriesMutation.isPending}
              >
                {importMemoriesMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Upload className="size-4" />
                )}
                导入
              </Button>
              {isMemoryListOpen ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => expireMutation.mutate()}
                    disabled={expireMutation.isPending}
                  >
                    {expireMutation.isPending ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Clock className="size-4" />
                    )}
                    清理过期
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => dedupMutation.mutate()}
                    disabled={dedupMutation.isPending}
                  >
                    {dedupMutation.isPending ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Copy className="size-4" />
                    )}
                    去重
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      if (
                        confirm("确定要压缩记忆吗？这将使用 LLM 合并相似记忆。")
                      ) {
                        summarizeMutation.mutate()
                      }
                    }}
                    disabled={summarizeMutation.isPending}
                  >
                    {summarizeMutation.isPending ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Minimize2 className="size-4" />
                    )}
                    压缩
                  </Button>
                </>
              ) : null}
              <Button size="sm" onClick={() => setIsAddDialogOpen(true)}>
                <Plus className="size-4" />
                添加记忆
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {!isMemoryListOpen ? (
            <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-center">
              <p className="text-sm text-muted-foreground">
                记忆列表已收起，展开后按 {MEMORY_PAGE_SIZE} 条一段读取。
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                当前统计 {stats?.total ?? 0} 条记忆
              </p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
                  <Input
                    placeholder="搜索记忆..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                    className="pl-9"
                  />
                </div>
                <Select
                  value={filterType}
                  onValueChange={(v) => setFilterType(v as MemoryType | "all")}
                >
                  <SelectTrigger className="w-32">
                    <Filter className="mr-2 size-4" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部</SelectItem>
                    {Object.entries(MEMORY_TYPE_LABELS).map(([type, label]) => (
                      <SelectItem key={type} value={type}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={filterStatus}
                  onValueChange={(v) =>
                    setFilterStatus(v as ManagedMemoryStatus | "all")
                  }
                >
                  <SelectTrigger className="w-36">
                    <SelectValue placeholder="状态" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部状态</SelectItem>
                    <SelectItem value="active">进行中</SelectItem>
                    <SelectItem value="completed">已完成</SelectItem>
                    <SelectItem value="resolved">已解决</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  variant={filterStatus === "active" ? "default" : "outline"}
                  onClick={() => {
                    setFilterStatus((current) =>
                      current === "active" ? "all" : "active",
                    )
                    if (
                      filterType !== "all" &&
                      filterType !== "task" &&
                      filterType !== "error"
                    ) {
                      setFilterType("all")
                    }
                  }}
                >
                  只看活跃
                </Button>
                {searchQuery && (
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      setSearchQuery("")
                      queryClient.invalidateQueries({
                        queryKey: ["memories", itemId],
                      })
                    }}
                  >
                    <X className="size-4" />
                  </Button>
                )}
              </div>

              {memoriesLoading || searchLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="size-8 animate-spin" />
                </div>
              ) : displayedMemories.length === 0 ? (
                <div className="py-8 text-center text-zinc-400">暂无记忆</div>
              ) : (
                <div className="max-h-96 space-y-2 overflow-y-auto">
                  {displayedMemories.map((memory) => {
                    const memoryStatus = memory.metadata.status
                    const statusAction = getStatusAction(memory)
                    const StatusActionIcon = statusAction?.icon
                    const statusTone =
                      memoryStatus === "active"
                        ? "border-emerald-500/30 bg-emerald-500/5"
                        : memoryStatus === "completed" ||
                            memoryStatus === "resolved"
                          ? "border-zinc-700 bg-zinc-900/60"
                          : "border-zinc-700 bg-zinc-800/50"

                    return (
                      <div
                        key={memory.id}
                        className={`flex items-start justify-between rounded-lg border p-3 ${statusTone}`}
                      >
                        <div className="flex-1">
                          <div className="mb-1 flex items-center gap-2">
                            <Badge
                              variant="secondary"
                              className={`${MEMORY_TYPE_COLORS[memory.metadata.memory_type]} text-white`}
                            >
                              {MEMORY_TYPE_LABELS[memory.metadata.memory_type]}
                            </Badge>
                            {memoryStatus && (
                              <Badge
                                variant="outline"
                                className={MEMORY_STATUS_COLORS[memoryStatus]}
                              >
                                {MEMORY_STATUS_LABELS[memoryStatus]}
                              </Badge>
                            )}
                            {memory.metadata.verified && (
                              <Badge
                                variant="outline"
                                className="border-emerald-500/30 text-emerald-300"
                              >
                                已验证
                              </Badge>
                            )}
                            <span className="text-xs text-zinc-400">
                              {memory.metadata.created_at &&
                                new Date(
                                  memory.metadata.created_at,
                                ).toLocaleString()}
                            </span>
                            {memory.metadata.updated_at &&
                              memory.metadata.updated_at !==
                                memory.metadata.created_at && (
                                <span className="text-xs text-zinc-500">
                                  更新:{" "}
                                  {new Date(
                                    memory.metadata.updated_at,
                                  ).toLocaleString()}
                                </span>
                              )}
                            {memory.metadata.expires_at && (
                              <span className="text-xs text-zinc-500">
                                过期:{" "}
                                {new Date(
                                  memory.metadata.expires_at,
                                ).toLocaleDateString()}
                              </span>
                            )}
                          </div>
                          <p className="text-sm">{memory.content}</p>
                          {memory.metadata.memory_key && (
                            <p className="mt-2 text-xs text-zinc-500">
                              key:{" "}
                              <span className="font-mono">
                                {memory.metadata.memory_key}
                              </span>
                            </p>
                          )}
                        </div>
                        <div className="flex gap-1">
                          {statusAction && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 gap-1"
                              onClick={() =>
                                updateMemoryStatusMutation.mutate({
                                  memoryId: memory.id,
                                  status: statusAction.status,
                                })
                              }
                              disabled={updateMemoryStatusMutation.isPending}
                            >
                              {StatusActionIcon && (
                                <StatusActionIcon className="size-3.5" />
                              )}
                              {statusAction.label}
                            </Button>
                          )}
                          <Button
                            size="icon"
                            variant="ghost"
                            className="size-8"
                            onClick={() => handleEditMemory(memory)}
                          >
                            <RefreshCw className="size-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="size-8 text-red-400 hover:text-red-300"
                            onClick={() =>
                              deleteMemoryMutation.mutate(memory.id)
                            }
                            disabled={deleteMemoryMutation.isPending}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {!searchQuery.trim() && hasNextPage ? (
                <div className="mt-3 flex justify-center">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => fetchNextPage()}
                    disabled={isFetchingNextPage}
                  >
                    {isFetchingNextPage ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : null}
                    加载更多
                  </Button>
                </div>
              ) : null}

              {!memoriesLoading && clearableMemoryCount > 0 && (
                <div className="mt-4 flex justify-between border-t border-zinc-700 pt-4">
                  <span className="text-sm text-zinc-400">
                    当前显示 {loadedMemoryCount} / 总计{" "}
                    {visibleTotalMemoryCount} 条记忆
                  </span>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => {
                      if (confirm("确定要清除所有记忆吗？此操作不可恢复。")) {
                        clearMemoriesMutation.mutate()
                      }
                    }}
                    disabled={clearMemoriesMutation.isPending}
                  >
                    {clearMemoriesMutation.isPending ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="size-4" />
                    )}
                    清除所有
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={isInstalledDialogOpen}
        onOpenChange={(open) => {
          setIsInstalledDialogOpen(open)
          if (!open) {
            setEditingInstalledSoftware(null)
            setInstalledSoftwareForm({ ...EMPTY_INSTALLED_SOFTWARE_FORM })
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingInstalledSoftware ? "编辑已安装软件" : "添加已安装软件"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>软件名称</Label>
                <Input
                  value={installedSoftwareForm.name}
                  onChange={(e) =>
                    setInstalledSoftwareForm((current) => ({
                      ...current,
                      name: e.target.value,
                    }))
                  }
                  placeholder="openjdk-21-jdk-headless"
                />
              </div>
              <div className="space-y-1.5">
                <Label>来源</Label>
                <Input
                  value={installedSoftwareForm.manager}
                  onChange={(e) =>
                    setInstalledSoftwareForm((current) => ({
                      ...current,
                      manager: e.target.value,
                    }))
                  }
                  placeholder="apt / pip / npm / manual"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>版本</Label>
              <Input
                value={installedSoftwareForm.version}
                onChange={(e) =>
                  setInstalledSoftwareForm((current) => ({
                    ...current,
                    version: e.target.value,
                  }))
                }
                placeholder="21"
              />
            </div>
            <div className="space-y-1.5">
              <Label>安装命令</Label>
              <Textarea
                value={installedSoftwareForm.command}
                onChange={(e) =>
                  setInstalledSoftwareForm((current) => ({
                    ...current,
                    command: e.target.value,
                  }))
                }
                rows={2}
                className="font-mono text-xs"
                placeholder="apt-get install -y openjdk-21-jdk-headless"
              />
            </div>
            <div className="space-y-1.5">
              <Label>备注</Label>
              <Textarea
                value={installedSoftwareForm.notes}
                onChange={(e) =>
                  setInstalledSoftwareForm((current) => ({
                    ...current,
                    notes: e.target.value,
                  }))
                }
                rows={3}
                placeholder="已通过 java -version 验证"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsInstalledDialogOpen(false)}
              disabled={saveInstalledSoftwareMutation.isPending}
            >
              取消
            </Button>
            <Button
              onClick={handleSaveInstalledSoftware}
              disabled={saveInstalledSoftwareMutation.isPending}
            >
              {saveInstalledSoftwareMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加记忆</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>记忆类型</Label>
              <Select
                value={newMemoryType}
                onValueChange={(v) => setNewMemoryType(v as MemoryType)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(MEMORY_TYPE_LABELS).map(([type, label]) => (
                    <SelectItem key={type} value={type}>
                      <div className="flex items-center gap-2">
                        <span
                          className={`size-2 rounded-full ${MEMORY_TYPE_COLORS[type as MemoryType]}`}
                        />
                        {label}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>记忆内容</Label>
              <Textarea
                value={newMemoryContent}
                onChange={(e) => setNewMemoryContent(e.target.value)}
                placeholder="输入记忆内容..."
                rows={4}
              />
            </div>
            <div>
              <Label>有效期（天）</Label>
              <Input
                type="number"
                value={newMemoryTtl}
                onChange={(e) => setNewMemoryTtl(Number(e.target.value))}
                min={1}
                max={365}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
              取消
            </Button>
            <Button
              onClick={handleAddMemory}
              disabled={addMemoryMutation.isPending}
            >
              {addMemoryMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                "添加"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑记忆</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>记忆类型</Label>
              <Badge
                variant="secondary"
                className={`${MEMORY_TYPE_COLORS[newMemoryType]} text-white`}
              >
                {MEMORY_TYPE_LABELS[newMemoryType]}
              </Badge>
            </div>
            <div>
              <Label>记忆内容</Label>
              <Textarea
                value={newMemoryContent}
                onChange={(e) => setNewMemoryContent(e.target.value)}
                placeholder="输入记忆内容..."
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsEditDialogOpen(false)}
            >
              取消
            </Button>
            <Button
              onClick={handleUpdateMemory}
              disabled={updateMemoryMutation.isPending}
            >
              {updateMemoryMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                "保存"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
