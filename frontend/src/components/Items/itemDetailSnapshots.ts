import type { ItemPublic } from "@/client"

const ITEM_SNAPSHOT_STORAGE_KEY = "termman:item-detail-snapshots"

type ItemSnapshotMap = Record<string, ItemPublic>

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

export function saveItemSnapshot(item: ItemPublic) {
  const snapshotMap = readSnapshotMap()
  snapshotMap[item.id] = item
  writeSnapshotMap(snapshotMap)
}

export function saveItemSnapshots(items: ItemPublic[]) {
  const snapshotMap = readSnapshotMap()

  for (const item of items) {
    snapshotMap[item.id] = item
  }

  writeSnapshotMap(snapshotMap)
}

export function createFallbackItem(
  itemId: string,
  source?: Partial<ItemPublic>,
): ItemPublic {
  const shortId = itemId.slice(0, 8).toUpperCase()

  return {
    title: source?.title?.trim() || `Item ${shortId}`,
    description:
      source?.description ??
      "Backend detail API has no response yet. This page is rendering with cached or placeholder data.",
    status: source?.status,
    config: source?.config,
    resource_usage: source?.resource_usage,
    log_path: source?.log_path,
    log_max_size_mb: source?.log_max_size_mb,
    socket_connection_type: source?.socket_connection_type,
    socket_host: source?.socket_host,
    socket_port: source?.socket_port,
    socket_connected: source?.socket_connected,
    socket_last_connected: source?.socket_last_connected,
    socket_unique_id: source?.socket_unique_id,
    api_key: source?.api_key,
    command: source?.command,
    executable_path: source?.executable_path,
    working_directory: source?.working_directory,
    id: source?.id ?? itemId,
    owner_id: source?.owner_id ?? "00000000-0000-0000-0000-000000000000",
    created_at: source?.created_at ?? null,
    updated_at: source?.updated_at ?? null,
  }
}
