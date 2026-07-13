import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CalendarClock,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
  type ScheduledTask,
  ScheduledTaskService,
  type ScheduledTaskType,
  type ScheduledTaskUpsertRequest,
} from "@/services/scheduled-tasks"

interface ScheduledTasksManagerProps {
  itemId: string
}

interface TaskForm {
  name: string
  instruction: string
  scheduleType: ScheduledTaskType
  runAt: string
  intervalSeconds: number
  timeOfDay: string
  timezone: string
  enabled: boolean
}

const EMPTY_FORM: TaskForm = {
  name: "",
  instruction: "",
  scheduleType: "interval",
  runAt: "",
  intervalSeconds: 3600,
  timeOfDay: "09:00",
  timezone: "Asia/Shanghai",
  enabled: true,
}

function toLocalDateTimeInput(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ""
  }
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function defaultOnceRunAt(): string {
  return toLocalDateTimeInput(new Date(Date.now() + 10 * 60_000))
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "-"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString("zh-CN", { hour12: false })
}

function scheduleLabel(task: ScheduledTask): string {
  if (task.schedule_type === "once") {
    return `执行一次 · ${formatDate(task.run_at)}`
  }
  if (task.schedule_type === "interval") {
    const seconds = task.interval_seconds ?? 0
    if (seconds % 3600 === 0) {
      return `每 ${seconds / 3600} 小时`
    }
    if (seconds % 60 === 0) {
      return `每 ${seconds / 60} 分钟`
    }
    return `每 ${seconds} 秒`
  }
  return `每天 ${task.time_of_day || "-"} · ${task.timezone}`
}

function taskToRequest(
  task: ScheduledTask,
  overrides: Partial<ScheduledTaskUpsertRequest> = {},
): ScheduledTaskUpsertRequest {
  return {
    task_id: task.id,
    name: task.name,
    instruction: task.instruction,
    schedule_type: task.schedule_type,
    run_at: task.run_at,
    interval_seconds: task.interval_seconds,
    time_of_day: task.time_of_day,
    timezone: task.timezone,
    enabled: task.enabled,
    ...overrides,
  }
}

function statusLabel(task: ScheduledTask): string {
  if (task.running || task.last_status === "running") {
    return "执行中"
  }
  if (task.last_status === "success") {
    return "成功"
  }
  if (task.last_status === "failed") {
    return "失败"
  }
  return "未执行"
}

export function ScheduledTasksManager({ itemId }: ScheduledTasksManagerProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null)
  const [form, setForm] = useState<TaskForm>({
    ...EMPTY_FORM,
    runAt: defaultOnceRunAt(),
  })

  const tasksQuery = useQuery({
    queryKey: ["scheduled-tasks", itemId],
    queryFn: () => ScheduledTaskService.list(itemId),
    refetchInterval: 10_000,
  })

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["scheduled-tasks", itemId] })

  const saveMutation = useMutation({
    mutationFn: (request: ScheduledTaskUpsertRequest) =>
      ScheduledTaskService.save(itemId, request),
    onSuccess: () => {
      showSuccessToast("定时任务已保存")
      setDialogOpen(false)
      setEditingTask(null)
      refresh()
    },
    onError: () => showErrorToast("保存定时任务失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => ScheduledTaskService.delete(itemId, taskId),
    onSuccess: () => {
      showSuccessToast("定时任务已删除")
      refresh()
    },
    onError: () => showErrorToast("删除定时任务失败"),
  })

  const openCreate = () => {
    setEditingTask(null)
    setForm({ ...EMPTY_FORM, runAt: defaultOnceRunAt() })
    setDialogOpen(true)
  }

  const openEdit = (task: ScheduledTask) => {
    setEditingTask(task)
    setForm({
      name: task.name,
      instruction: task.instruction,
      scheduleType: task.schedule_type,
      runAt: task.run_at
        ? toLocalDateTimeInput(task.run_at)
        : defaultOnceRunAt(),
      intervalSeconds: task.interval_seconds || 3600,
      timeOfDay: task.time_of_day || "09:00",
      timezone: task.timezone || "Asia/Shanghai",
      enabled: task.enabled,
    })
    setDialogOpen(true)
  }

  const submit = () => {
    if (!form.name.trim() || !form.instruction.trim()) {
      showErrorToast("请输入任务名称和执行内容")
      return
    }
    const request: ScheduledTaskUpsertRequest = {
      task_id: editingTask?.id,
      name: form.name.trim(),
      instruction: form.instruction.trim(),
      schedule_type: form.scheduleType,
      timezone: form.timezone.trim() || "Asia/Shanghai",
      enabled: form.enabled,
    }
    if (form.scheduleType === "once") {
      const runAt = new Date(form.runAt)
      if (Number.isNaN(runAt.getTime())) {
        showErrorToast("请选择有效的执行时间")
        return
      }
      request.run_at = runAt.toISOString()
    } else if (form.scheduleType === "interval") {
      request.interval_seconds = Math.max(
        10,
        Number(form.intervalSeconds) || 10,
      )
    } else {
      request.time_of_day = form.timeOfDay
    }
    saveMutation.mutate(request)
  }

  const tasks = tasksQuery.data?.items ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-2">
          <CalendarClock className="mt-0.5 size-5 text-amber-500" />
          <div>
            <h2 className="text-lg font-semibold">定时任务</h2>
            <p className="text-sm text-muted-foreground">
              到点后作为定时任务送入 Agent；也可由 Agent
              使用读、写、删工具管理。
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => refresh()}
            disabled={tasksQuery.isFetching}
          >
            {tasksQuery.isFetching ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            刷新
          </Button>
          <Button type="button" size="sm" onClick={openCreate}>
            <Plus className="size-4" />
            新建任务
          </Button>
        </div>
      </div>

      {tasksQuery.isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="size-6 animate-spin" />
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-md border border-dashed bg-muted/20 px-4 py-10 text-center text-sm text-muted-foreground">
          暂无定时任务
        </div>
      ) : (
        <div className="divide-y rounded-md border">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="grid gap-3 p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
            >
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{task.name}</span>
                  <Badge variant={task.enabled ? "secondary" : "outline"}>
                    {task.enabled ? "已启用" : "已停用"}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={
                      task.last_status === "failed"
                        ? "border-red-500/40 text-red-500"
                        : task.last_status === "success"
                          ? "border-emerald-500/40 text-emerald-500"
                          : ""
                    }
                  >
                    {statusLabel(task)}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {scheduleLabel(task)}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-sm">
                  {task.instruction}
                </p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>下次：{formatDate(task.next_run_at)}</span>
                  <span>上次：{formatDate(task.last_finished_at)}</span>
                  <span>执行：{task.run_count || 0} 次</span>
                </div>
                {task.last_error ? (
                  <p className="text-xs text-red-500">{task.last_error}</p>
                ) : null}
              </div>
              <div className="flex justify-end gap-1">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-8"
                  title={task.enabled ? "停用" : "启用"}
                  onClick={() =>
                    saveMutation.mutate(
                      taskToRequest(task, { enabled: !task.enabled }),
                    )
                  }
                  disabled={saveMutation.isPending || task.running}
                >
                  {task.enabled ? (
                    <Pause className="size-4" />
                  ) : (
                    <Play className="size-4" />
                  )}
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-8"
                  title="编辑"
                  onClick={() => openEdit(task)}
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-8 text-red-500 hover:text-red-500"
                  title="删除"
                  onClick={() => {
                    if (confirm(`删除定时任务“${task.name}”？`)) {
                      deleteMutation.mutate(task.id)
                    }
                  }}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editingTask ? "编辑定时任务" : "新建定时任务"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="scheduled-task-name">名称</Label>
              <Input
                id="scheduled-task-name"
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder="例如：每天检查服务器状态"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="scheduled-task-instruction">执行内容</Label>
              <Textarea
                id="scheduled-task-instruction"
                rows={4}
                value={form.instruction}
                onChange={(event) =>
                  setForm({ ...form, instruction: event.target.value })
                }
                placeholder="到点后发送给 Agent 的任务指令"
              />
            </div>
            <div className="space-y-1.5">
              <Label>计划</Label>
              <Select
                value={form.scheduleType}
                onValueChange={(value) =>
                  setForm({ ...form, scheduleType: value as ScheduledTaskType })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="once">执行一次</SelectItem>
                  <SelectItem value="interval">固定间隔</SelectItem>
                  <SelectItem value="daily">每天执行</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {form.scheduleType === "once" ? (
              <div className="space-y-1.5">
                <Label htmlFor="scheduled-task-run-at">执行时间</Label>
                <Input
                  id="scheduled-task-run-at"
                  type="datetime-local"
                  value={form.runAt}
                  onChange={(event) =>
                    setForm({ ...form, runAt: event.target.value })
                  }
                />
              </div>
            ) : null}

            {form.scheduleType === "interval" ? (
              <div className="space-y-1.5">
                <Label htmlFor="scheduled-task-interval">间隔秒数</Label>
                <Input
                  id="scheduled-task-interval"
                  type="number"
                  min={10}
                  value={form.intervalSeconds}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      intervalSeconds: Number(event.target.value),
                    })
                  }
                />
              </div>
            ) : null}

            {form.scheduleType === "daily" ? (
              <div className="space-y-1.5">
                <Label htmlFor="scheduled-task-time">每天时间</Label>
                <Input
                  id="scheduled-task-time"
                  type="time"
                  value={form.timeOfDay}
                  onChange={(event) =>
                    setForm({ ...form, timeOfDay: event.target.value })
                  }
                />
              </div>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="scheduled-task-timezone">时区</Label>
              <Input
                id="scheduled-task-timezone"
                value={form.timezone}
                onChange={(event) =>
                  setForm({ ...form, timezone: event.target.value })
                }
                placeholder="Asia/Shanghai"
              />
            </div>

            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id="scheduled-task-enabled"
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm({ ...form, enabled: Boolean(checked) })
                }
              />
              <Label htmlFor="scheduled-task-enabled">保存后启用</Label>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDialogOpen(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={submit}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
