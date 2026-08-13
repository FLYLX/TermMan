import { useCallback, useEffect, useState } from "react"
import {
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Server,
  Square,
  Trash2,
} from "lucide-react"

import { OpenAPI } from "@/client/core/OpenAPI"
import useCustomToast from "@/hooks/useCustomToast"

export type WsServer = {
  server_id: string
  item_id: string
  name: string
  host: string
  port: number
  token: string
  heartbeat_interval: number
  message_format: "json"
  running: boolean
  client_count: number
  url: string
}

async function wsRequest<T>(
  itemId: string,
  path = "",
  init: RequestInit = {},
): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/items/${itemId}/websocket-servers${path}`,
    { ...init, headers },
  )
  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => undefined)
    : await response.text().catch(() => "")
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : String(payload || `HTTP ${response.status}`)
    throw new Error(detail)
  }
  return payload as T
}

function connectionUrl(server: WsServer): string {
  let host = server.host
  if (host === "0.0.0.0" || host === "::") {
    try {
      const apiUrl = new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
      host = apiUrl.hostname || window.location.hostname || "127.0.0.1"
    } catch {
      host = window.location.hostname || "127.0.0.1"
    }
  }
  return `ws://${host}:${server.port}/?token=${encodeURIComponent(server.token)}`
}

export function TerminalWsPanel({
  itemId,
  itemTitle,
}: {
  itemId: string
  itemTitle: string
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [servers, setServers] = useState<WsServer[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [actionId, setActionId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    name: `${itemTitle} WS`,
    host: "0.0.0.0",
    port: "",
    token: "",
    heartbeat_interval: "30",
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await wsRequest<{ servers: WsServer[] }>(itemId)
      setServers(data.servers || [])
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [itemId, showErrorToast])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    const name = form.name.trim()
    if (!name) {
      showErrorToast("请输入名称")
      return
    }
    const port = form.port.trim() ? Number(form.port.trim()) : null
    if (port !== null && (!Number.isInteger(port) || port < 1 || port > 65535)) {
      showErrorToast("端口必须是 1-65535")
      return
    }
    const heartbeat = form.heartbeat_interval.trim()
      ? Number(form.heartbeat_interval.trim())
      : null
    if (heartbeat !== null && (!Number.isFinite(heartbeat) || heartbeat < 1 || heartbeat > 300)) {
      showErrorToast("心跳必须是 1-300 秒")
      return
    }
    setCreating(true)
    try {
      await wsRequest<WsServer>(itemId, "", {
        method: "POST",
        body: JSON.stringify({
          name,
          host: form.host.trim() || null,
          port,
          token: form.token.trim() || null,
          heartbeat_interval: heartbeat,
          message_format: "json",
        }),
      })
      setForm((c) => ({ ...c, name: `${itemTitle} WS`, port: "", token: "" }))
      setShowCreate(false)
      showSuccessToast("WebSocket server 已创建")
      await load()
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  const action = async (serverId: string, kind: "start" | "stop" | "delete") => {
    setActionId(serverId)
    try {
      if (kind === "delete") {
        await wsRequest(itemId, `/${serverId}`, { method: "DELETE" })
      } else {
        await wsRequest(itemId, `/${serverId}/${kind}`, { method: "POST" })
      }
      showSuccessToast("操作成功")
      await load()
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "操作失败")
    } finally {
      setActionId(null)
    }
  }

  return (
    <div className="space-y-3 text-sm text-[#1f1f1f]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-bold">
          <Server className="size-4" />
          WebSocket Server
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="sketch-mini-box flex items-center gap-1 px-2 py-1"
            onClick={() => setShowCreate((v) => !v)}
          >
            <Plus className="size-3.5" /> 新建
          </button>
          <button
            type="button"
            className="sketch-mini-box flex items-center gap-1 px-2 py-1"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> 刷新
          </button>
        </div>
      </div>

      {showCreate ? (
        <div className="sketch-box sketch-b space-y-2 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className="rounded border border-[#3a3a3a] bg-white px-2 py-1"
              placeholder="名称"
              value={form.name}
              onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))}
            />
            <input
              className="rounded border border-[#3a3a3a] bg-white px-2 py-1"
              placeholder="Host"
              value={form.host}
              onChange={(e) => setForm((c) => ({ ...c, host: e.target.value }))}
            />
            <input
              className="rounded border border-[#3a3a3a] bg-white px-2 py-1"
              placeholder="端口（留空自动分配）"
              value={form.port}
              onChange={(e) => setForm((c) => ({ ...c, port: e.target.value }))}
            />
            <input
              className="rounded border border-[#3a3a3a] bg-white px-2 py-1"
              placeholder="Token（留空自动生成）"
              value={form.token}
              onChange={(e) => setForm((c) => ({ ...c, token: e.target.value }))}
            />
            <input
              className="rounded border border-[#3a3a3a] bg-white px-2 py-1"
              placeholder="心跳秒数（默认 30）"
              value={form.heartbeat_interval}
              onChange={(e) => setForm((c) => ({ ...c, heartbeat_interval: e.target.value }))}
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="sketch-mini-box px-2 py-1"
              onClick={() => setShowCreate(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="sketch-mini-box flex items-center gap-1 bg-[#e9e9e6] px-2 py-1"
              onClick={() => void create()}
              disabled={creating}
            >
              {creating ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
              创建
            </button>
          </div>
        </div>
      ) : null}

      {loading && servers.length === 0 ? (
        <div className="flex items-center gap-2 py-8 text-xs text-[#565654]">
          <Loader2 className="size-4 animate-spin" /> 正在加载…
        </div>
      ) : servers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#3a3a3a] px-4 py-8 text-center text-xs text-[#565654]">
          还没有 WebSocket Server
        </div>
      ) : (
        <div className="space-y-2">
          {servers.map((server) => (
            <div key={server.server_id} className="sketch-box sketch-c p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-bold">
                  {server.name}
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${
                      server.running
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-zinc-200 text-zinc-700"
                    }`}
                  >
                    {server.running ? "运行中" : "已停止"} · {server.client_count} 客户端
                  </span>
                </div>
                <div className="flex gap-1.5">
                  {server.running ? (
                    <button
                      type="button"
                      className="sketch-mini-box flex items-center gap-1 px-2 py-1"
                      disabled={actionId === server.server_id}
                      onClick={() => void action(server.server_id, "stop")}
                    >
                      <Square className="size-3" /> 停止
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="sketch-mini-box flex items-center gap-1 px-2 py-1"
                      disabled={actionId === server.server_id}
                      onClick={() => void action(server.server_id, "start")}
                    >
                      <Play className="size-3" /> 启动
                    </button>
                  )}
                  <button
                    type="button"
                    className="sketch-mini-box flex items-center gap-1 px-2 py-1 hover:bg-red-50"
                    disabled={actionId === server.server_id}
                    onClick={() => void action(server.server_id, "delete")}
                  >
                    <Trash2 className="size-3" /> 删除
                  </button>
                </div>
              </div>
              <div className="mt-1.5 break-all font-mono text-[11px] text-[#565654]">
                {connectionUrl(server)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
