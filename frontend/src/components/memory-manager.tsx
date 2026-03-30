import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Brain,
  Plus,
  Trash2,
  Search,
  RefreshCw,
  Copy,
  Clock,
  Filter,
  X,
  Loader2,
  Minimize2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import {
  MemoryService,
  MEMORY_TYPE_LABELS,
  MEMORY_TYPE_COLORS,
  type Memory,
  type MemoryType,
} from "@/services/memory"

interface MemoryManagerProps {
  itemId: string
}

export function MemoryManager({ itemId }: MemoryManagerProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [searchQuery, setSearchQuery] = useState("")
  const [filterType, setFilterType] = useState<MemoryType | "all">("all")
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [editingMemory, setEditingMemory] = useState<Memory | null>(null)
  const [newMemoryContent, setNewMemoryContent] = useState("")
  const [newMemoryType, setNewMemoryType] = useState<MemoryType>("fact")
  const [newMemoryTtl, setNewMemoryTtl] = useState(30)

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["memory-stats", itemId],
    queryFn: () => MemoryService.getMemoryStats(itemId),
  })

  const { data: memoriesData, isLoading: memoriesLoading } = useQuery({
    queryKey: ["memories", itemId, filterType],
    queryFn: () =>
      MemoryService.getAllMemories(itemId, filterType === "all" ? undefined : filterType),
  })

  const { data: searchResults, refetch: performSearch, isLoading: searchLoading } = useQuery({
    queryKey: ["memory-search", itemId, searchQuery],
    queryFn: () =>
      MemoryService.searchMemories(itemId, {
        query: searchQuery,
        n_results: 10,
      }),
    enabled: false,
  })

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
        showErrorToast("重复记忆已跳过")
      }
      setIsAddDialogOpen(false)
      setNewMemoryContent("")
      setNewMemoryType("fact")
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
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
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
    },
    onError: () => showErrorToast("更新记忆失败"),
  })

  const deleteMemoryMutation = useMutation({
    mutationFn: (memoryId: string) => MemoryService.deleteMemory(itemId, memoryId),
    onSuccess: () => {
      showSuccessToast("记忆已删除")
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    },
    onError: () => showErrorToast("删除记忆失败"),
  })

  const clearMemoriesMutation = useMutation({
    mutationFn: () => MemoryService.clearMemories(itemId),
    onSuccess: () => {
      showSuccessToast("所有记忆已清除")
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    },
    onError: () => showErrorToast("清除记忆失败"),
  })

  const expireMutation = useMutation({
    mutationFn: () => MemoryService.expireMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(`已清理 ${result.count} 条过期记忆`)
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    },
    onError: () => showErrorToast("清理过期记忆失败"),
  })

  const dedupMutation = useMutation({
    mutationFn: () => MemoryService.deduplicateMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(`已去重 ${result.count} 条记忆`)
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    },
    onError: () => showErrorToast("去重失败"),
  })

  const summarizeMutation = useMutation({
    mutationFn: () => MemoryService.summarizeMemories(itemId),
    onSuccess: (result) => {
      showSuccessToast(result.message)
      queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
      queryClient.invalidateQueries({ queryKey: ["memory-stats", itemId] })
    },
    onError: () => showErrorToast("压缩记忆失败"),
  })

  const handleSearch = () => {
    if (searchQuery.trim()) {
      performSearch()
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

  const displayedMemories = searchQuery.trim() && searchResults ? searchResults.memories : memoriesData?.memories || []

  return (
    <div className="space-y-4">
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
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold">{stats.total}</div>
                <div className="text-sm text-zinc-400">总记忆数</div>
              </div>
              <div className="rounded-lg bg-zinc-800 p-3">
                <div className="text-2xl font-bold text-red-400">{stats.expired_count}</div>
                <div className="text-sm text-zinc-400">已过期</div>
              </div>
              <div className="col-span-2 rounded-lg bg-zinc-800 p-3">
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
            <div className="flex gap-2">
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
                  if (confirm("确定要压缩记忆吗？这将使用 LLM 合并相似记忆。")) {
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
              <Button size="sm" onClick={() => setIsAddDialogOpen(true)}>
                <Plus className="size-4" />
                添加记忆
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex gap-2">
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
            {searchQuery && (
              <Button
                size="icon"
                variant="ghost"
                onClick={() => {
                  setSearchQuery("")
                  queryClient.invalidateQueries({ queryKey: ["memories", itemId] })
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
              {displayedMemories.map((memory) => (
                <div
                  key={memory.id}
                  className="flex items-start justify-between rounded-lg border border-zinc-700 bg-zinc-800/50 p-3"
                >
                  <div className="flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge
                        variant="secondary"
                        className={`${MEMORY_TYPE_COLORS[memory.metadata.memory_type]} text-white`}
                      >
                        {MEMORY_TYPE_LABELS[memory.metadata.memory_type]}
                      </Badge>
                      <span className="text-xs text-zinc-400">
                        {memory.metadata.created_at &&
                          new Date(memory.metadata.created_at).toLocaleString()}
                      </span>
                      {memory.metadata.expires_at && (
                        <span className="text-xs text-zinc-500">
                          过期: {new Date(memory.metadata.expires_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                    <p className="text-sm">{memory.content}</p>
                  </div>
                  <div className="flex gap-1">
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
                      onClick={() => deleteMemoryMutation.mutate(memory.id)}
                      disabled={deleteMemoryMutation.isPending}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {memoriesData && memoriesData.count > 0 && (
            <div className="mt-4 flex justify-between border-t border-zinc-700 pt-4">
              <span className="text-sm text-zinc-400">共 {memoriesData.count} 条记忆</span>
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
        </CardContent>
      </Card>

      <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加记忆</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>记忆类型</Label>
              <Select value={newMemoryType} onValueChange={(v) => setNewMemoryType(v as MemoryType)}>
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
            <Button onClick={handleAddMemory} disabled={addMemoryMutation.isPending}>
              {addMemoryMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : "添加"}
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
            <Button variant="outline" onClick={() => setIsEditDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleUpdateMemory} disabled={updateMemoryMutation.isPending}>
              {updateMemoryMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
