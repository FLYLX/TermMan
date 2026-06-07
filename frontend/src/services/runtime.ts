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

export async function getBackendRuntimeStats() {
  return apiRequest<BackendRuntimeStatsResponse>(
    "/api/v1/utils/backend-runtime/",
  )
}
