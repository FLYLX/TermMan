import { useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useLocation, useNavigate } from "@tanstack/react-router"
import {
  BookOpen,
  Code2,
  Home,
  Layers,
  LogOut,
  Package,
  Puzzle,
  Server,
  UserRound,
  Users,
} from "lucide-react"

import { useI18n } from "@/components/locale-provider"
import useAuth from "@/hooks/useAuth"
import { McpService, ItemHandlersService } from "@/client"
import { getPluginsQueryOptions, isPluginEnabled } from "@/lib/plugins-api"

type HangTagItem = {
  icon: typeof Home
  title: string
  path: string
  feature?: "robot" | "mcp"
}

const baseItems: HangTagItem[] = [
  { icon: Home, title: "nav.dashboard", path: "/" },
  { icon: Layers, title: "nav.itemHandlers", path: "/item-handlers" },
  { icon: Puzzle, title: "nav.plugins", path: "/plugins" },
  { icon: BookOpen, title: "nav.knowledge", path: "/knowledge" },
  { icon: Package, title: "nav.skills", path: "/skills" },
  { icon: Server, title: "nav.mcpServers", path: "/mcp-servers", feature: "mcp" },
  { icon: Code2, title: "nav.pluginDev", path: "/plugin-dev" },
]

export function HangTagNav() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user: currentUser, logout } = useAuth()
  const { t, locale, setLocale } = useI18n()
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const closeTimerRef = useRef<number | null>(null)

  const cancelScheduledClose = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }
  const scheduleClose = () => {
    cancelScheduledClose()
    closeTimerRef.current = window.setTimeout(() => setUserMenuOpen(false), 250)
  }

  const { data: plugins } = useQuery({
    ...getPluginsQueryOptions(),
    enabled: Boolean(currentUser),
  })
  const { data: mcpServers } = useQuery({
    queryFn: () => McpService.listMcpServers(),
    queryKey: ["mcp-servers"],
    enabled: Boolean(currentUser),
  })

  const hasRobotPlugin = isPluginEnabled(plugins, "TermPaws.robot")
  const hasExternalMcpServers = Boolean(
    mcpServers?.data?.some((server: { name?: string }) => server.name !== "local"),
  )

  const visibleItems = baseItems.filter((item) => {
    if (item.feature === "robot") {
      return hasRobotPlugin
    }
    if (item.feature === "mcp") {
      return hasExternalMcpServers
    }
    return true
  })
  const items: HangTagItem[] = currentUser?.is_superuser
    ? [
        ...visibleItems,
        { icon: Users, title: "nav.admin", path: "/admin" },
      ]
    : visibleItems

  const pathname = location.pathname
  const isActive = (path: string) =>
    path === "/" ? pathname === "/" : pathname.startsWith(path)

  const goTo = async (path: string) => {
    if (path === "/item-handlers") {
      // 直接进第一个调度器详情页；没有则停留列表页
      try {
        const handlers = (await ItemHandlersService.readItemHandlers({
          skip: 0,
          limit: 1,
        })) as any
        const first = Array.isArray(handlers)
          ? handlers[0]
          : (handlers?.data ?? [])[0]
        if (first?.id) {
          await navigate({
            to: "/item-handlers/$itemHandlerId",
            params: { itemHandlerId: String(first.id) },
          })
          return
        }
      } catch {
        // fall through to list page
      }
    }
    await navigate({ to: path })
  }

  return (
    <div className="tag-rail">
      {items.map((item, index) => {
        const Icon = item.icon
        const active = isActive(item.path)
        return (
          <button
            key={item.path}
            type="button"
            onClick={() => void goTo(item.path)}
            className={`hang-tag ${active ? "hang-tag-active" : ""}`}
            style={{ "--tilt": index % 2 === 0 ? "-1.6deg" : "1.8deg" } as any}
            title={t(item.title as any)}
          >
            <span className="tag-hole" />
            <Icon className="size-4" />
            <span>{t(item.title as any)}</span>
          </button>
        )
      })}
      <div
        className="tag-user-anchor"
        onMouseEnter={cancelScheduledClose}
        onMouseLeave={scheduleClose}
      >
        <button
          type="button"
          onClick={() => setUserMenuOpen((v) => !v)}
          className="hang-tag"
          style={{ "--tilt": "1.2deg" } as any}
          title={currentUser?.email || ""}
        >
          <span className="tag-hole" />
          <UserRound className="size-4" />
          <span>{currentUser?.email?.split("@")[0] || "账户"}</span>
        </button>
        {userMenuOpen ? (
          <div className="tag-user-menu">
            <button
              type="button"
              className="sketch-mini-box mb-2 flex w-full items-center justify-center gap-2 px-2 py-1 hover:bg-amber-50"
              onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
            >
              {locale === "zh" ? "English" : "中文"}
            </button>
            <button
              type="button"
              className="sketch-mini-box flex w-full items-center gap-2 px-2 py-1 hover:bg-red-50"
              onClick={() => {
                setUserMenuOpen(false)
                logout()
                void navigate({ to: "/login" })
              }}
            >
              <LogOut className="size-4" />
              退出登录
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
