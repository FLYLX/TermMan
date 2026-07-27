import { useQuery } from "@tanstack/react-query"
import { OpenAPI } from "@/client/core/OpenAPI"
import { BarChart3 } from "lucide-react"

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

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export function TokenUsagePanel({ itemId }: { itemId: string }) {
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

      {data.last_seen && (
        <p className="text-xs text-muted-foreground">
          最后活跃: {data.last_seen}
        </p>
      )}
    </div>
  )
}