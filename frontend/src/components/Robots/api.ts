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

export type UpdateRobotPayload = Partial<CreateRobotPayload>

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

export async function updateRobot(
  robotId: string,
  payload: UpdateRobotPayload,
) {
  return apiRequest<RobotRecord>(`/api/v1/robots/${robotId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
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

export type BridgeHealthResponse = {
  loaded_robot_count: number
  connected_bot_count: number
  platforms: string[]
  connected_identities: string[]
  robots: Record<string, { identity: string; connected: boolean }>
  error?: string
  connected?: boolean
}

export type RobotConnectionStatus = {
  robot_id: string
  identity?: string
  connected: boolean
  platform?: string
  reason?: string
  error?: string
}

export function getBridgeHealthQueryKey() {
  return ["robot-bridge-health"] as const
}

export function getRobotConnectionQueryKey(robotId: string) {
  return ["robot-connection", robotId] as const
}

export async function getBridgeHealth() {
  return apiRequest<BridgeHealthResponse>("/api/v1/robots/bridge/health")
}

export async function getRobotConnectionStatus(robotId: string) {
  return apiRequest<RobotConnectionStatus>(
    `/api/v1/robots/${robotId}/connection`,
  )
}

export type RobotDiagnoseResult = {
  robot_id: string
  robot_name: string
  robot_enabled: boolean
  platform: string
  checked_at?: string
  overall_status: "ok" | "degraded"
  chain: {
    robot_config: {
      status: string
      app_id: string | null
      provider: string
    }
    qq_to_bridge: {
      status: string
      connected: boolean
      identity?: string
      backend_reachable?: boolean
      error?: string
      stale_error?: string | null
      stale_error_at?: string | null
      bridge_checked_at?: string | null
      live?: boolean
    }
    items: Array<{
      item_id: string
      item_title: string
      allow_chat: boolean
      daemon: {
        status: string
        online: boolean
      }
    }>
  }
}

export function getRobotDiagnoseQueryKey(robotId: string) {
  return ["robot-diagnose", robotId] as const
}

export async function diagnoseRobotChain(robotId: string) {
  return apiRequest<RobotDiagnoseResult>(`/api/v1/robots/${robotId}/diagnose`)
}

export type RobotDebugEvent = {
  timestamp: string
  direction: string
  event: string
  status: string
  message?: string | null
  payload: Record<string, unknown>
}

export type RobotDebugInfo = {
  robot: {
    id: string
    name: string
    platform: string
    provider: string
    is_enabled: boolean
    app_id: string | null
  }
  bridge: {
    url: string
    status: string
    loaded_robot_count: number
    connected_bot_count: number
    connected: boolean
    identity?: string | null
    error?: string | null
  }
  diagnostics?: {
    event_count: number
    last_event_at?: string | null
    qq_event_hint?: string | null
  }
  events: RobotDebugEvent[]
}

export function getRobotDebugQueryKey(robotId: string) {
  return ["robot-debug", robotId] as const
}

export async function getRobotDebug(robotId: string) {
  return apiRequest<RobotDebugInfo>(`/api/v1/robots/${robotId}/debug`)
}

export async function reloadRobotBridge(robotId: string) {
  return apiRequest<{ success: boolean; message?: string; error?: string }>(
    `/api/v1/robots/${robotId}/reload`,
    { method: "POST" },
  )
}

export async function createRobotDebugTestEvent(robotId: string) {
  return apiRequest<{ success: boolean }>(
    `/api/v1/robots/${robotId}/debug/test-event`,
    { method: "POST" },
  )
}
