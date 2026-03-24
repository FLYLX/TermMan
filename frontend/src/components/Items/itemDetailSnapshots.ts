import type { ItemPublic } from "@/client"

const ITEM_SNAPSHOT_STORAGE_KEY = "termman:item-detail-snapshots"

type ItemWithExtras = ItemPublic & {
  daemon_url?: string
  daemon_id?: string
  daemon_online?: boolean
  daemon_status?: string
  connected_users?: Record<string, { user_uuid: string; ip: string }>
  token?: string
}

type ItemSnapshotMap = Record<string, ItemWithExtras>

function canUseStorage() {
  return (
    typeof window !== "undefined" && typeof window.localStorage !== "undefined"
  )
}

function readSnapshotMap(): ItemSnapshotMap {
  if (!canUseStorage()) {
    return {}
  }

  try {
    const rawValue = window.localStorage.getItem(ITEM_SNAPSHOT_STORAGE_KEY)
    if (!rawValue) {
      return {}
    }

    return JSON.parse(rawValue) as ItemSnapshotMap
  } catch {
    return {}
  }
}

function writeSnapshotMap(snapshotMap: ItemSnapshotMap) {
  if (!canUseStorage()) {
    return
  }

  window.localStorage.setItem(
    ITEM_SNAPSHOT_STORAGE_KEY,
    JSON.stringify(snapshotMap),
  )
}

export function getStoredItemSnapshot(itemId: string) {
  return readSnapshotMap()[itemId]
}

export function saveItemSnapshot(item: ItemWithExtras) {
  const snapshotMap = readSnapshotMap()
  snapshotMap[item.id] = item
  writeSnapshotMap(snapshotMap)
}

export function saveItemSnapshots(items: ItemWithExtras[]) {
  const snapshotMap = readSnapshotMap()

  for (const item of items) {
    snapshotMap[item.id] = item
  }

  writeSnapshotMap(snapshotMap)
}

export function createFallbackItem(
  itemId: string,
  source?: Partial<ItemWithExtras>,
): ItemWithExtras {
  const shortId = itemId.slice(0, 8).toUpperCase()

  return {
    title: source?.title?.trim() || `Item ${shortId}`,
    description:
      source?.description ??
      "Backend detail API has no response yet. This page is rendering with cached or placeholder data.",
    status: source?.status,
    log_max_size_mb: source?.log_max_size_mb,
    socket_host: source?.socket_host,
    socket_port: source?.socket_port,
    socket_connected: source?.socket_connected,
    socket_last_connected: source?.socket_last_connected,
    api_key: source?.api_key,
    command: source?.command,
    working_directory: source?.working_directory,
    input_filter_enabled: source?.input_filter_enabled,
    input_filter_mode: source?.input_filter_mode,
    input_noise_patterns: source?.input_noise_patterns,
    input_event_patterns: source?.input_event_patterns,
    output_filter_enabled: source?.output_filter_enabled,
    output_filter_mode: source?.output_filter_mode,
    output_command_list: source?.output_command_list,
    output_sensitive_patterns: source?.output_sensitive_patterns,
    output_rate_limit: source?.output_rate_limit,
    id: source?.id ?? itemId,
    owner_id: source?.owner_id ?? "00000000-0000-0000-0000-000000000000",
    created_at: source?.created_at ?? null,
    updated_at: source?.updated_at ?? null,
    daemon_url: source?.daemon_url,
    connected_users: source?.connected_users,
    token: source?.token,
  }
}
