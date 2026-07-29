import { MemoryService as GeneratedMemoryService } from "@/client"
import type { CancelablePromise } from "@/client/core/CancelablePromise"
import { OpenAPI } from "@/client/core/OpenAPI"
import { request as __request } from "@/client/core/request"

export type MemoryType = "fact" | "preference" | "error" | "context"
export type ManagedMemoryStatus = "active" | "resolved"

export interface Memory {
  id: string
  content: string
  metadata: {
    item_id: string
    memory_type: MemoryType
    created_at: string
    expires_at?: string | null
    updated_at?: string
    status?: ManagedMemoryStatus
    memory_key?: string
    verified?: boolean
    [key: string]: unknown
  }
  distance?: number
}

export interface MemoryStats {
  total: number
  by_type: Record<MemoryType, number>
  expired_count: number
  memory_types: Record<MemoryType, string>
  status_counts: {
    error: {
      active: number
      resolved: number
    }
  }
}

export interface MemoryCreateRequest {
  content: string
  memory_type?: MemoryType
  metadata?: Record<string, unknown>
  ttl_days?: number
}

export interface MemoryUpdateRequest {
  content?: string
  metadata?: Record<string, unknown>
}

export interface MemoryStatusUpdateRequest {
  status: ManagedMemoryStatus
}

export interface MemorySearchRequest {
  query: string
  n_results?: number
  memory_type?: MemoryType
}

export interface MemoryListOptions {
  offset?: number
  limit?: number
  status?: ManagedMemoryStatus
}

export interface MemoryListResponse {
  memories: Memory[]
  count: number
  offset: number
  limit: number
  has_more: boolean
}

export interface MemoryExportPayload {
  version: number
  exported_at: string
  item_id: string
  count: number
  memories: Memory[]
}

export interface MemoryImportItem {
  id?: string | null
  content: string
  metadata?: Record<string, unknown>
}

export interface MemoryImportRequest {
  version?: number
  memories: MemoryImportItem[]
}

export interface MemoryImportResponse {
  message: string
  imported: number
  skipped: number
  errors: string[]
  memory_ids: string[]
}

export const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  fact: "事实",
  preference: "偏好",
  error: "错误",
  context: "上下文",
}

export const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  fact: "bg-blue-500",
  preference: "bg-purple-500",
  error: "bg-red-500",
  context: "bg-yellow-500",
}

export const MEMORY_STATUS_LABELS: Record<ManagedMemoryStatus, string> = {
  active: "进行中",
  resolved: "已解决",
}

export const MEMORY_STATUS_COLORS: Record<ManagedMemoryStatus, string> = {
  active: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  resolved: "bg-sky-500/15 text-sky-300 border-sky-500/30",
}

export class MemoryService {
  public static getAllMemories(
    itemId: string,
    memoryType?: MemoryType,
    options: MemoryListOptions = {},
  ): CancelablePromise<MemoryListResponse> {
    const query: Record<string, unknown> = {}
    if (memoryType) {
      query.memory_type = memoryType
    }
    if (options.offset !== undefined) {
      query.offset = options.offset
    }
    if (options.limit !== undefined) {
      query.limit = options.limit
    }
    if (options.status) {
      query.memory_status = options.status
    }
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories",
      path: { item_id: itemId },
      query: Object.keys(query).length > 0 ? query : undefined,
    })
  }

  public static exportMemories(
    itemId: string,
    memoryType?: MemoryType,
  ): CancelablePromise<MemoryExportPayload> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories/export",
      path: { item_id: itemId },
      query: memoryType ? { memory_type: memoryType } : undefined,
    })
  }

  public static importMemories(
    itemId: string,
    request: MemoryImportRequest,
  ): CancelablePromise<MemoryImportResponse> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/import",
      path: { item_id: itemId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static getMemoryStats(itemId: string): CancelablePromise<MemoryStats> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories/stats",
      path: { item_id: itemId },
    })
  }

  public static getMemoryTypes(): CancelablePromise<{
    types: Record<MemoryType, string>
  }> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories/types",
      path: { item_id: "dummy" },
    })
  }

  public static searchMemories(
    itemId: string,
    request: MemorySearchRequest,
  ): CancelablePromise<{ memories: Memory[] }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/search",
      path: { item_id: itemId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static addMemory(
    itemId: string,
    request: MemoryCreateRequest,
  ): CancelablePromise<{ memory_id: string | null; message: string }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories",
      path: { item_id: itemId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static updateMemory(
    itemId: string,
    memoryId: string,
    request: MemoryUpdateRequest,
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "PUT",
      url: "/api/v1/memory/{item_id}/memories/{memory_id}",
      path: { item_id: itemId, memory_id: memoryId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static updateMemoryStatus(
    itemId: string,
    memoryId: string,
    request: MemoryStatusUpdateRequest,
  ): CancelablePromise<{ message: string; memory: Memory }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/{memory_id}/status",
      path: { item_id: itemId, memory_id: memoryId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static deleteMemory(
    itemId: string,
    memoryId: string,
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/memory/{item_id}/memories/{memory_id}",
      path: { item_id: itemId, memory_id: memoryId },
    })
  }

  public static clearMemories(
    itemId: string,
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/memory/{item_id}/memories",
      path: { item_id: itemId },
    })
  }

  public static expireMemories(
    itemId: string,
  ): CancelablePromise<{ message: string; count: number }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/expire",
      path: { item_id: itemId },
    })
  }

  public static deduplicateMemories(
    itemId: string,
  ): CancelablePromise<{ message: string; count: number }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/deduplicate",
      path: { item_id: itemId },
    })
  }

  public static summarizeMemories(
    itemId: string,
    threshold: number = 10,
  ): CancelablePromise<{
    summarized: number
    summaries_created: number
    message: string
  }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/summarize",
      path: { item_id: itemId },
      query: { threshold },
    })
  }

  public static getChatSession = GeneratedMemoryService.getChatSession
  public static saveChatSession = GeneratedMemoryService.saveChatSession
  public static clearChatSession = GeneratedMemoryService.clearChatSession
}
