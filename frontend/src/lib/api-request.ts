import { OpenAPI } from "@/client"

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init?.headers || {})
  headers.set("Authorization", `Bearer ${token}`)

  if (
    init?.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${OpenAPI.BASE}${path}`, {
    ...init,
    headers,
  })

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

  return response.json() as Promise<T>
}
