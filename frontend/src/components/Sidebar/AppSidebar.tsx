import { useQuery } from "@tanstack/react-query"
import {
  BookOpen,
  Bot,
  Code2,
  Home,
  Layers,
  Package,
  Puzzle,
  Server,
  Terminal,
  Users,
} from "lucide-react"

import { McpService } from "@/client"
import { SidebarAppearance } from "@/components/Common/Appearance"
import { SidebarLanguageSwitcher } from "@/components/Common/LanguageSwitcher"
import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { getPluginsQueryOptions, isPluginEnabled } from "@/lib/plugins-api"
import { type Item, Main } from "./Main"
import { User } from "./User"

type SidebarItem = Item & {
  feature?: "robot" | "mcp"
}

const baseItems: SidebarItem[] = [
  { icon: Home, title: "nav.dashboard", path: "/" },
  { icon: Terminal, title: "nav.items", path: "/items" },
  { icon: Layers, title: "nav.itemHandlers", path: "/item-handlers" },
  { icon: Bot, title: "nav.robots", path: "/robots", feature: "robot" },
  { icon: Puzzle, title: "nav.plugins", path: "/plugins" },
  { icon: BookOpen, title: "nav.knowledge", path: "/knowledge" },
  { icon: Package, title: "nav.skills", path: "/skills" },
  { icon: Server, title: "nav.mcpServers", path: "/mcp-servers", feature: "mcp" },
  { icon: Code2, title: "nav.pluginDev", path: "/plugin-dev" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { t } = useI18n()
  const { data: plugins } = useQuery({
    ...getPluginsQueryOptions(),
    enabled: Boolean(currentUser),
  })
  const { data: mcpServers } = useQuery({
    queryFn: () => McpService.listMcpServers(),
    queryKey: ["mcp-servers"],
    enabled: Boolean(currentUser),
  })

  const hasRobotPlugin = isPluginEnabled(plugins, "termman.robot")
  const hasExternalMcpServers = Boolean(
    mcpServers?.data?.some((server: { name?: string }) => server.name !== "local"),
  )
  const visibleBaseItems = baseItems.filter((item) => {
    if (item.feature === "robot") {
      return hasRobotPlugin
    }
    if (item.feature === "mcp") {
      return hasExternalMcpServers
    }
    return true
  })

  const items = currentUser?.is_superuser
    ? [...visibleBaseItems, { icon: Users, title: "nav.admin", path: "/admin" }]
    : visibleBaseItems

  const translatedItems = items.map((item) => ({
    ...item,
    title: t(item.title as any),
  }))

  return (
    <Sidebar collapsible="icon" variant="floating">
      <SidebarHeader className="px-4 py-5 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-2">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={translatedItems} />
      </SidebarContent>
      <SidebarFooter className="border-t border-white/8 pt-3">
        <SidebarAppearance />
        <SidebarLanguageSwitcher />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
