import { apiRequest } from "@/lib/api-request"

export type RobotConfig = {
  credentials?: Record<string, unknown>
  options?: Record<string, unknown>
}

export type RobotRecord = {
  id: string
  name: string
  platform: string
  protocol: string
  provider: string
  app_id: string | null
  app_secret: string | null
  bot_token: string | null
  use_websocket: boolean
  is_enabled: boolean
  config: RobotConfig | null
  owner_id: string
  created_at?: string | null
  updated_at?: string | null
}

export type RobotListResponse = {
  data: RobotRecord[]
  count: number
}

export type CreateRobotBindingPayload = {
  item_id: string
  allow_chat?: boolean
  receive_filtered_output?: boolean
  chat_alias?: string | null
  is_default_target?: boolean
}

export type UpdateRobotBindingPayload = {
  allow_chat?: boolean
  receive_filtered_output?: boolean
  chat_alias?: string | null
  is_default_target?: boolean
}

export type RobotBindingRecord = {
  robot_id: string
  item_id: string
  item_title: string
  allow_chat: boolean
  receive_filtered_output: boolean
  chat_alias: string | null
  route_key: string
  is_default_target: boolean
}

export type RobotPlatformField = {
  key: string
  label: string
  required: boolean
  secret: boolean
}

export type RobotPlatformRecord = {
  id: string
  label: string
  provider: string
  description: string
  fields: RobotPlatformField[]
}

export type CreateRobotPayload = {
  name: string
  platform?: string
  protocol?: string
  provider?: string
  app_id?: string | null
  app_secret?: string | null
  bot_token?: string | null
  use_websocket?: boolean
  is_enabled?: boolean
  config?: RobotConfig
}

export function getRobotsQueryKey() {
  return ["robots"] as const
}

export function getRobotPlatformsQueryKey() {
  return ["robot-platforms"] as const
}

export function getRobotQueryKey(robotId: string) {
  return ["robot", robotId] as const
}

export function getRobotBindingsQueryKey(robotId: string) {
  return ["robot-bindings", robotId] as const
}

export async function listRobots() {
  return apiRequest<RobotListResponse>("/api/v1/robots/")
}

export async function readRobot(robotId: string) {
  return apiRequest<RobotRecord>(`/api/v1/robots/${robotId}`)
}

export async function listRobotPlatforms() {
  return apiRequest<RobotPlatformRecord[]>("/api/v1/robots/platforms")
}

export async function createRobot(payload: CreateRobotPayload) {
  return apiRequest<RobotRecord>("/api/v1/robots/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function deleteRobot(robotId: string) {
  return apiRequest<{ message: string }>(`/api/v1/robots/${robotId}`, {
    method: "DELETE",
  })
}

export async function listRobotBindings(robotId: string) {
  return apiRequest<RobotBindingRecord[]>(`/api/v1/robots/${robotId}/items`)
}

export async function createRobotBinding(
  robotId: string,
  payload: CreateRobotBindingPayload,
) {
  return apiRequest<RobotBindingRecord>(`/api/v1/robots/${robotId}/items`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateRobotBinding(
  robotId: string,
  itemId: string,
  payload: UpdateRobotBindingPayload,
) {
  return apiRequest<RobotBindingRecord>(
    `/api/v1/robots/${robotId}/items/${itemId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  )
}

export async function deleteRobotBinding(robotId: string, itemId: string) {
  return apiRequest<{ message: string }>(
    `/api/v1/robots/${robotId}/items/${itemId}`,
    {
      method: "DELETE",
    },
  )
}
