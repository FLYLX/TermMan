import { OpenAPI } from "@/client/core/OpenAPI"

export type PluginItem = {
  plugin_id: string
  name: string
  version: string
  description: string
  builtin: boolean
  category: string
  enabled: boolean
  default_enabled: boolean
  configurable: boolean
  capabilities: string[]
}

export type PluginListResponse = {
  data: PluginItem[]
  count: number
}

export async function requestPluginApi<T>(
  path = "",
  init: RequestInit = {},
): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${OpenAPI.BASE}/api/v1/plugins${path}`, {
    ...init,
    headers,
  })
  const payload = await response.json().catch(() => undefined)

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : `HTTP ${response.status}`
    throw new Error(detail)
  }

  return payload as T
}

export function getPluginsQueryOptions() {
  return {
    queryFn: () => requestPluginApi<PluginListResponse>("/"),
    queryKey: ["plugins"],
  }
}

export function isPluginEnabled(
  plugins: PluginListResponse | undefined,
  pluginId: string,
): boolean {
  return Boolean(
    plugins?.data.some(
      (plugin) => plugin.plugin_id === pluginId && plugin.enabled,
    ),
  )
}
