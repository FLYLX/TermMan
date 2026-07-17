import type { CancelablePromise } from "@/client/core/CancelablePromise"
import { OpenAPI } from "@/client/core/OpenAPI"
import { request as __request } from "@/client/core/request"

export const PENDING_REPLY_QUEUE_EVENT = "termman:pending-replies-changed"

export function notifyPendingReplyQueueChanged(itemId: string): void {
  window.dispatchEvent(
    new CustomEvent(PENDING_REPLY_QUEUE_EVENT, {
      detail: { itemId },
    }),
  )
}

export interface PendingReplyWorkflow {
  workflow_id?: string
  objective?: string
  status?: string
  current_step?: string
  latest_progress?: string
  current_step_index?: number
  steps?: Array<{
    step_id?: string
    title: string
    status: string
    evidence?: string
    last_error?: string
    recovery?: boolean
  }>
}

export interface PendingReplyDestination {
  id: string
  type: "qq" | "web" | "terminal" | string
  label: string
  requester: string
  status: string
  last_error?: string
}

export interface PendingReplyEntry {
  id: string
  item_id: string
  requester: string
  request_summary: string
  task_plan: string[]
  destination_type: "qq" | "web" | "terminal" | string
  destination_label: string
  destinations?: PendingReplyDestination[]
  status: string
  awaiting_kind?: string
  awaiting_key?: string
  last_error?: string
  created_at: string
  updated_at: string
  workflow?: PendingReplyWorkflow | null
}

export const PendingReplyService = {
  list(
    itemId: string,
  ): CancelablePromise<{ items: PendingReplyEntry[]; count: number }> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/pending-replies/{item_id}",
      path: { item_id: itemId },
    })
  },

  delete(
    itemId: string,
    entryId: string,
  ): CancelablePromise<{ message: string }> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/pending-replies/{item_id}/{entry_id}",
      path: { item_id: itemId, entry_id: entryId },
    })
  },

  send(
    itemId: string,
    entryId: string,
    content: string,
  ): CancelablePromise<{ message: string; destination: string }> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/pending-replies/{item_id}/{entry_id}/send",
      path: { item_id: itemId, entry_id: entryId },
      body: { content },
      mediaType: "application/json",
    })
  },
}
