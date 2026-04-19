import { apiRequest } from "@/lib/api-request"

export type ItemHandlerLlmStatusItem = {
  item_handler_id: string
  status: "connected" | "error" | "not_configured"
  reachable: boolean
  message: string | null
  checked_at: string
  cached: boolean
}

export type ItemHandlerLlmStatusListResponse = {
  data: ItemHandlerLlmStatusItem[]
  count: number
}

export function getItemHandlerLlmStatusQueryKey() {
  return ["item-handler-llm-status"] as const
}

export async function listItemHandlerLlmStatuses(force = false) {
  const query = force ? "?force=true" : ""
  return apiRequest<ItemHandlerLlmStatusListResponse>(
    `/api/v1/item-handlers/llm/status${query}`,
  )
}
