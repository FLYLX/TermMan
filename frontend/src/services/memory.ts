import { MemoryService as GeneratedMemoryService } from "@/client"
import type { CancelablePromise } from "@/client/core/CancelablePromise"
import { request as __request } from "@/client/core/request"
import { OpenAPI } from "@/client/core/OpenAPI"

export type MemoryType = "fact" | "preference" | "task" | "error" | "context"

export interface Memory {
  id: string
  content: string
  metadata: {
    item_id: string
    memory_type: MemoryType
    created_at: string
    expires_at: string
    [key: string]: unknown
  }
  distance?: number
}

export interface MemoryStats {
  total: number
  by_type: Record<MemoryType, number>
  expired_count: number
  memory_types: Record<MemoryType, string>
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

export interface MemorySearchRequest {
  query: string
  n_results?: number
  memory_type?: MemoryType
}

export const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  fact: "事实",
  preference: "偏好",
  task: "任务",
  error: "错误",
  context: "上下文",
}

export const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  fact: "bg-blue-500",
  preference: "bg-purple-500",
  task: "bg-green-500",
  error: "bg-red-500",
  context: "bg-yellow-500",
}

export class MemoryService {
  public static getAllMemories(
    itemId: string,
    memoryType?: MemoryType
  ): CancelablePromise<{ memories: Memory[]; count: number }> {
    const query: Record<string, unknown> = {}
    if (memoryType) {
      query.memory_type = memoryType
    }
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories",
      path: { item_id: itemId },
      query: Object.keys(query).length > 0 ? query : undefined,
    })
  }

  public static getMemoryStats(itemId: string): CancelablePromise<MemoryStats> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories/stats",
      path: { item_id: itemId },
    })
  }

  public static getMemoryTypes(): CancelablePromise<{ types: Record<MemoryType, string> }> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/memories/types",
      path: { item_id: "dummy" },
    })
  }

  public static searchMemories(
    itemId: string,
    request: MemorySearchRequest
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
    request: MemoryCreateRequest
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
    request: MemoryUpdateRequest
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "PUT",
      url: "/api/v1/memory/{item_id}/memories/{memory_id}",
      path: { item_id: itemId, memory_id: memoryId },
      body: request,
      mediaType: "application/json",
    })
  }

  public static deleteMemory(
    itemId: string,
    memoryId: string
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/memory/{item_id}/memories/{memory_id}",
      path: { item_id: itemId, memory_id: memoryId },
    })
  }

  public static clearMemories(itemId: string): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/memory/{item_id}/memories",
      path: { item_id: itemId },
    })
  }

  public static expireMemories(itemId: string): CancelablePromise<{ message: string; count: number }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/expire",
      path: { item_id: itemId },
    })
  }

  public static deduplicateMemories(itemId: string): CancelablePromise<{ message: string; count: number }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/memories/deduplicate",
      path: { item_id: itemId },
    })
  }

  public static summarizeMemories(
    itemId: string,
    threshold: number = 10
  ): CancelablePromise<{ summarized: number; summaries_created: number; message: string }> {
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
