import { Fragment, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { OpenAPI } from "@/client/core/OpenAPI"
import { AlertCircle, BarChart3, Check, ChevronRight, Circle, Loader2 } from "lucide-react"

interface ModelUsage {
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  turns: number
}

interface TokenStats {
  item_id: string
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_turns: number
  first_seen: string
  last_seen: string
  models: ModelUsage[]
}

interface PlanStep {
  step: string
  status: string
}

interface TaskUsage {
  reply_ticket_id: string
  source_type: string
  source_label: string
  request_message: string
  plan: PlanStep[]
  ticket_status: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  turns: number
  first_seen: string
  last_seen: string
}

interface TaskUsageResponse {
  item_id: string
  tasks: TaskUsage[]
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatDuration(firstSeen: string, lastSeen: string): string {
  if (!firstSeen || !lastSeen) return "-"
  const start = Date.parse(firstSeen.replace(" ", "T"))
  const end = Date.parse(lastSeen.replace(" ", "T"))
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "-"
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h${minutes % 60}m`
}

function TaskStatusIcon({ status }: { status: string }) {
  if (status === "delivered" || status === "completed") {
    return <Check className="size-3.5 shrink-0 text-emerald-400" />
  }
  if (status === "failed") {
    return <AlertCircle className="size-3.5 shrink-0 text-red-400" />
  }
  if (status === "pending" || status === "running" || status === "sending") {
    return <Loader2 className="size-3.5 shrink-0 animate-spin text-sky-400" />
  }
  return <Circle className="size-3.5 shrink-0 text-slate-500" />
}

export function TokenUsagePanel({ itemId }: { itemId: string }) {
  const [expandedTask, setExpandedTask] = useState<string | null>(null)

  const { data, isLoading } = useQuery<TokenStats>({
    queryKey: ["token-usage", itemId],
    queryFn: async () => {
      const token = localStorage.getItem("access_token") || ""
      const res = await fetch(`${OpenAPI.BASE}/api/v1/items/${itemId}/token-usage`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error("Failed to fetch")
      return res.json()
    },
    refetchInterval: 10000,
  })

  const { data: taskData } = useQuery<TaskUsageResponse>({
    queryKey: ["token-usage-by-task", itemId],
    queryFn: async () => {
      const token = localStorage.getItem("access_token") || ""
      const res = await fetch(
        `${OpenAPI.BASE}/api/v1/items/${itemId}/token-usage/by-task`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      if (!res.ok) throw new Error("Failed to fetch")
      return res.json()
    },
    refetchInterval: 10000,
  })

  if (isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">加载中...</div>
  }

  if (!data || data.total_turns === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-8 text-muted-foreground">
        <BarChart3 className="h-8 w-8 opacity-40" />
        <p className="text-sm">暂无 Token 使用记录</p>
        <p className="text-xs">Agent 对话产生调用后会自动统计</p>
      </div>
    )
  }

  const tasks = (taskData?.tasks ?? []).slice(0, 20)

  return (
    <div className="space-y-4 p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">总 Token</p>
          <p className="text-lg font-semibold">{formatTokens(data.total_tokens)}</p>
        </div>
        <div className="rounded-lg border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">Prompt</p>
          <p className="text-lg font-semibold">{formatTokens(data.total_prompt_tokens)}</p>
        </div>
        <div className="rounded-lg border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">Completion</p>
          <p className="text-lg font-semibold">{formatTokens(data.total_completion_tokens)}</p>
        </div>
        <div className="rounded-lg border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">总轮次</p>
          <p className="text-lg font-semibold">{data.total_turns}</p>
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium">按任务（plan）</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-3 py-2 text-left font-medium">任务</th>
                <th className="px-3 py-2 text-left font-medium">来源</th>
                <th className="px-3 py-2 text-right font-medium">步骤</th>
                <th className="px-3 py-2 text-right font-medium">Prompt</th>
                <th className="px-3 py-2 text-right font-medium">Completion</th>
                <th className="px-3 py-2 text-right font-medium">总计</th>
                <th className="px-3 py-2 text-right font-medium">轮次</th>
                <th className="px-3 py-2 text-right font-medium">耗时</th>
              </tr>
            </thead>
            <tbody>
              {tasks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-4 text-center text-muted-foreground">
                    暂无任务记录（新产生的任务才会按 ticket 统计）
                  </td>
                </tr>
              ) : (
                tasks.map((t) => {
                  const done = (t.plan || []).filter((s) => s.status === "completed").length
                  const expanded = expandedTask === t.reply_ticket_id
                  return (
                    <Fragment key={t.reply_ticket_id}>
                      <tr
                        className="cursor-pointer border-b hover:bg-muted/30"
                        onClick={() =>
                          setExpandedTask(expanded ? null : t.reply_ticket_id)
                        }
                      >
                        <td className="max-w-64 px-3 py-2">
                          <div className="flex items-center gap-1.5">
                            <ChevronRight
                              className={`size-3 shrink-0 text-slate-500 transition-transform ${expanded ? "rotate-90" : ""}`}
                            />
                            <TaskStatusIcon status={t.ticket_status} />
                            <span className="truncate text-xs">
                              {t.request_message || t.source_label || t.reply_ticket_id.slice(0, 8)}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          {t.source_type || "-"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs text-sky-400">
                          {t.plan && t.plan.length > 0 ? `${done}/${t.plan.length}` : "-"}
                        </td>
                        <td className="px-3 py-2 text-right">{formatTokens(t.prompt_tokens)}</td>
                        <td className="px-3 py-2 text-right">{formatTokens(t.completion_tokens)}</td>
                        <td className="px-3 py-2 text-right font-medium text-amber-500">
                          {formatTokens(t.total_tokens)}
                        </td>
                        <td className="px-3 py-2 text-right">{t.turns}</td>
                        <td className="px-3 py-2 text-right text-xs text-muted-foreground">
                          {formatDuration(t.first_seen, t.last_seen)}
                        </td>
                      </tr>
                      {expanded ? (
                        <tr key={`${t.reply_ticket_id}-detail`} className="border-b last:border-0 bg-muted/20">
                          <td colSpan={8} className="px-6 py-2">
                            {t.plan && t.plan.length > 0 ? (
                              <div className="space-y-1">
                                {t.plan.map((s, i) => (
                                  <div key={i} className="flex items-center gap-2 text-xs">
                                    {s.status === "completed" ? (
                                      <Check className="size-3 text-emerald-400" />
                                    ) : s.status === "in_progress" ? (
                                      <Loader2 className="size-3 animate-spin text-sky-400" />
                                    ) : (
                                      <Circle className="size-3 text-slate-500" />
                                    )}
                                    <span className="text-slate-300">{s.step}</span>
                                    <span className="text-slate-600">{s.status}</span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <span className="text-xs text-muted-foreground">该任务没有 plan（简单任务直接执行）</span>
                            )}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium">按模型</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-3 py-2 text-left font-medium">模型</th>
                <th className="px-3 py-2 text-right font-medium">Prompt</th>
                <th className="px-3 py-2 text-right font-medium">Completion</th>
                <th className="px-3 py-2 text-right font-medium">总计</th>
                <th className="px-3 py-2 text-right font-medium">轮次</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-3 py-2 font-mono text-xs">{m.model}</td>
                  <td className="px-3 py-2 text-right">{formatTokens(m.prompt_tokens)}</td>
                  <td className="px-3 py-2 text-right">{formatTokens(m.completion_tokens)}</td>
                  <td className="px-3 py-2 text-right font-medium">{formatTokens(m.total_tokens)}</td>
                  <td className="px-3 py-2 text-right">{m.turns}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.last_seen && (
        <p className="text-xs text-muted-foreground">
          最后活跃: {data.last_seen}
        </p>
      )}
    </div>
  )
}
