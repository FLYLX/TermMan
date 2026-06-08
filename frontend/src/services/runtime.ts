import { apiRequest } from "@/lib/api-request"

export type RuntimeProcessStats = {
  pid: number
  ppid: number | null
  name: string | null
  command: string | null
  rss_bytes: number | null
  vms_bytes: number | null
  rss_anon_bytes: number | null
  rss_file_bytes: number | null
  rss_shmem_bytes: number | null
  swap_bytes: number | null
  cpu_percent: number | null
  cpu_user_seconds: number | null
  cpu_system_seconds: number | null
  thread_count: number | null
  open_fds: number | null
  started_at: number | null
  uptime_seconds: number | null
}

export type RuntimeAggregateStats = {
  process_count: number
  rss_bytes: number | null
  vms_bytes: number | null
  rss_anon_bytes: number | null
  rss_file_bytes: number | null
  rss_shmem_bytes: number | null
  swap_bytes: number | null
  cpu_percent: number | null
  cpu_user_seconds: number | null
  cpu_system_seconds: number | null
  thread_count: number | null
  open_fds: number | null
}

export type BackendRuntimeStatsResponse = {
  service: string
  sampled_at: number
  hostname: string
  ip_addresses: string[]
  platform: string
  python_version: string
  cpu_count: number | null
  cpu_model: string | null
  cpu_frequency_mhz: number | null
  memory_total_bytes: number | null
  memory_available_bytes: number | null
  memory_used_bytes: number | null
  memory_percent: number | null
  collection_scope: string
  current_pid: number
  aggregate: RuntimeAggregateStats
  current_process: RuntimeProcessStats
  processes: RuntimeProcessStats[]
}

export type RuntimeServiceStats = {
  service: string
  label: string
  kind: string
  status: string
  url: string | null
  runtime: BackendRuntimeStatsResponse | null
  error: string | null
  metadata: Record<string, unknown>
}

export type TermManRuntimeTotals = {
  service_count: number
  ok_count: number
  process_count: number
  rss_bytes: number | null
  vms_bytes: number | null
  cpu_percent: number | null
  thread_count: number | null
  open_fds: number | null
}

export type TermManRuntimeStatsResponse = {
  sampled_at: number
  services: RuntimeServiceStats[]
  totals: TermManRuntimeTotals
}

export async function getBackendRuntimeStats() {
  return apiRequest<BackendRuntimeStatsResponse>(
    "/api/v1/utils/backend-runtime/",
  )
}

export async function getTermManRuntimeStats() {
  return apiRequest<TermManRuntimeStatsResponse>(
    "/api/v1/utils/termman-runtime/",
  )
}
