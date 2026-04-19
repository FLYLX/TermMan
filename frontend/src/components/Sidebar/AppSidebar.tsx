import {
  BookOpen,
  Bot,
  Home,
  Layers,
  Package,
  Server,
  Terminal,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { SidebarLanguageSwitcher } from "@/components/Common/LanguageSwitcher"
import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"
import { BackendPerformance } from "@/components/Sidebar/BackendPerformance"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "nav.dashboard", path: "/" },
  { icon: Terminal, title: "nav.items", path: "/items" },
  { icon: Layers, title: "nav.itemHandlers", path: "/item-handlers" },
  { icon: Bot, title: "nav.robots", path: "/robots" },
  { icon: BookOpen, title: "nav.knowledge", path: "/knowledge" },
  { icon: Package, title: "nav.skills", path: "/skills" },
  { icon: Server, title: "nav.mcpServers", path: "/mcp-servers" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { t } = useI18n()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "nav.admin", path: "/admin" }]
    : baseItems

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
        <BackendPerformance enabled={Boolean(currentUser?.is_superuser)} />
        <SidebarAppearance />
        <SidebarLanguageSwitcher />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
