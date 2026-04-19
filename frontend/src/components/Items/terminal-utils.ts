import type { ItemPublic } from "@/client"

export type TerminalItem = ItemPublic & {
  daemon_id?: string
  daemon_online?: boolean
  daemon_status?: string
  daemon_url?: string
  connected_users?: Record<string, { user_uuid: string; ip: string }>
  token?: string
}

export type DaemonGroup = {
  key: string
  label: string
  host?: string | null
  port?: number | null
  apiKey?: string | null
  apiKeyMasked: string
  daemonStatus?: string
  daemonOnline: boolean
  isConfigured: boolean
  items: TerminalItem[]
}

export const CUSTOM_DAEMON_KEY = "__custom_daemon__"
export const UNASSIGNED_DAEMON_KEY = "__unassigned_daemon__"

export function formatDaemonLabel(
  host?: string | null,
  port?: number | string | null,
) {
  const normalizedHost = host?.trim() || "localhost"
  return port ? `${normalizedHost}:${port}` : normalizedHost
}

export function maskApiKey(apiKey?: string | null) {
  if (!apiKey) {
    return "not set"
  }

  if (apiKey.length <= 4) {
    return apiKey
  }

  return `••••${apiKey.slice(-4)}`
}

export function buildDaemonKey({
  host,
  port,
  apiKey,
}: {
  host?: string | null
  port?: number | string | null
  apiKey?: string | null
}) {
  if (!host || !port || !apiKey) {
    return UNASSIGNED_DAEMON_KEY
  }

  return `${host}:${port}:${apiKey}`
}

export function buildTerminalTitle({
  command,
  workingDirectory,
  daemonLabel,
}: {
  command?: string | null
  workingDirectory?: string | null
  daemonLabel?: string | null
}) {
  const commandLabel = (command || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)
    .join(" ")
  const directoryLabel = (workingDirectory || "")
    .split(/[\\/]/)
    .filter(Boolean)
    .slice(-1)[0]

  const base =
    directoryLabel && commandLabel
      ? `${directoryLabel} · ${commandLabel}`
      : directoryLabel || commandLabel || "terminal"

  return `${base}${daemonLabel ? ` @ ${daemonLabel}` : ""}`.slice(0, 96)
}

export function groupItemsByDaemon(items: TerminalItem[]) {
  const groups = new Map<string, DaemonGroup>()

  for (const item of items) {
    const key = buildDaemonKey({
      host: item.socket_host,
      port: item.socket_port,
      apiKey: item.api_key,
    })
    const isConfigured = key !== UNASSIGNED_DAEMON_KEY
    const label = isConfigured
      ? formatDaemonLabel(item.socket_host, item.socket_port)
      : "Unassigned daemon"

    const existing = groups.get(key)
    if (existing) {
      existing.items.push(item)
      existing.daemonOnline =
        existing.daemonOnline || Boolean(item.daemon_online)
      existing.daemonStatus = existing.daemonStatus || item.daemon_status
      continue
    }

    groups.set(key, {
      key,
      label,
      host: item.socket_host,
      port: item.socket_port,
      apiKey: item.api_key,
      apiKeyMasked: maskApiKey(item.api_key),
      daemonStatus: item.daemon_status,
      daemonOnline: Boolean(item.daemon_online),
      isConfigured,
      items: [item],
    })
  }

  return Array.from(groups.values()).sort((left, right) => {
    if (left.isConfigured !== right.isConfigured) {
      return left.isConfigured ? -1 : 1
    }

    if (left.daemonOnline !== right.daemonOnline) {
      return left.daemonOnline ? -1 : 1
    }

    return left.label.localeCompare(right.label)
  })
}
