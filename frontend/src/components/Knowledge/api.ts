import { OpenAPI } from "@/client"
import { apiRequest } from "@/lib/api-request"

export type KnowledgeFileItem = {
  path: string
  name: string
  size: number | null
  modified_at: number | null
  enabled: boolean
  indexed: boolean
  missing: boolean
  chunk_count: number
}

export type KnowledgeFileListResponse = {
  data: KnowledgeFileItem[]
  count: number
  enabled_count: number
}

export function getKnowledgeLibraryQueryKey() {
  return ["knowledge-library"] as const
}

export function getItemHandlerKnowledgeQueryKey(itemHandlerId: string) {
  return ["itemHandler-knowledge", itemHandlerId] as const
}

function buildAuthHeaders() {
  const token = localStorage.getItem("access_token") || ""
  return new Headers({ Authorization: `Bearer ${token}` })
}

export function encodePathForRoute(path: string) {
  return path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")
}

export function formatBytes(value: number | null) {
  if (value === null) {
    return "-"
  }
  if (value < 1024) {
    return `${value} B`
  }

  const units = ["KB", "MB", "GB"]
  let size = value
  let unitIndex = -1
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`
}

export async function listKnowledgeLibraryFiles() {
  return apiRequest<KnowledgeFileListResponse>("/api/v1/knowledge/files")
}

export async function listItemHandlerKnowledgeFiles(itemHandlerId: string) {
  return apiRequest<KnowledgeFileListResponse>(
    `/api/v1/item-handlers/${itemHandlerId}/knowledge/files`,
  )
}

export async function uploadKnowledgeLibraryFiles(files: File[]) {
  const formData = new FormData()
  for (const file of files) {
    formData.append("files", file)
  }

  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/knowledge/files/upload`,
    {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    },
  )

  if (!response.ok) {
    let detail = "Request failed"
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }

  return response.json()
}

export async function deleteKnowledgeLibraryFile(filePath: string) {
  return apiRequest(`/api/v1/knowledge/files/${encodePathForRoute(filePath)}`, {
    method: "DELETE",
  })
}

export async function downloadKnowledgeLibraryFile(file: KnowledgeFileItem) {
  const response = await fetch(
    `${OpenAPI.BASE}/api/v1/knowledge/files/download/${encodePathForRoute(file.path)}`,
    {
      headers: buildAuthHeaders(),
    },
  )

  if (!response.ok) {
    let detail = "Request failed"
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }

  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = file.name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => {
    window.URL.revokeObjectURL(url)
  }, 0)
}
