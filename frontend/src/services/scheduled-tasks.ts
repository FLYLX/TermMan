import type { CancelablePromise } from "@/client/core/CancelablePromise"
import { OpenAPI } from "@/client/core/OpenAPI"
import { request as __request } from "@/client/core/request"

export type ScheduledTaskType = "once" | "interval" | "daily"
export type ScheduledTaskStatus = "never" | "running" | "success" | "failed"

export interface ScheduledTask {
  id: string
  name: string
  instruction: string
  schedule_type: ScheduledTaskType
  run_at?: string
  interval_seconds?: number
  time_of_day?: string
  timezone: string
  enabled: boolean
  running?: boolean
  next_run_at?: string | null
  last_started_at?: string
  last_finished_at?: string
  last_status?: ScheduledTaskStatus
  last_error?: string
  run_count?: number
  failure_count?: number
  created_at: string
  updated_at: string
}

export interface ScheduledTaskUpsertRequest {
  task_id?: string
  name: string
  instruction: string
  schedule_type: ScheduledTaskType
  run_at?: string
  interval_seconds?: number
  time_of_day?: string
  timezone?: string
  enabled?: boolean
}

export const ScheduledTaskService = {
  list(
    itemId: string,
  ): CancelablePromise<{ items: ScheduledTask[]; count: number }> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/memory/{item_id}/scheduled-tasks",
      path: { item_id: itemId },
    })
  },

  save(
    itemId: string,
    request: ScheduledTaskUpsertRequest,
  ): CancelablePromise<{ item: ScheduledTask; message: string }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/memory/{item_id}/scheduled-tasks",
      path: { item_id: itemId },
      body: request,
      mediaType: "application/json",
    })
  },

  delete(
    itemId: string,
    taskId: string,
  ): CancelablePromise<{ message: string; count: number }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/memory/{item_id}/scheduled-tasks/{task_id}",
      path: { item_id: itemId, task_id: taskId },
    })
  },
}
