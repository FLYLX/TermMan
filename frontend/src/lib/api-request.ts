import { OpenAPI } from "@/client"

export class ApiRequestError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiRequestError"
    this.status = status
  }
}

function handleAuthFailure(status: number, detail: string) {
  const isMissingUser = status === 404 && detail === "User not found"
  if (status !== 401 && !isMissingUser) {
    return
  }

  localStorage.removeItem("access_token")
  if (window.location.pathname !== "/login") {
    window.location.href = "/login"
  }
}

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
    handleAuthFailure(response.status, detail)
    throw new ApiRequestError(detail, response.status)
  }

  return response.json() as Promise<T>
}
