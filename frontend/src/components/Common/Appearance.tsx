import { Monitor, Moon, Sun } from "lucide-react"

import { useI18n } from "@/components/locale-provider"
import { type Theme, useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

type LucideIcon = React.FC<React.SVGProps<SVGSVGElement>>

const ICON_MAP: Record<Theme, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
}

export const SidebarAppearance = () => {
  const { isMobile } = useSidebar()
  const { setTheme, theme } = useTheme()
  const { t } = useI18n()
  const Icon = ICON_MAP[theme]

  return (
    <SidebarMenuItem>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuButton
            tooltip={t("common.appearance")}
            data-testid="theme-button"
          >
            <Icon className="size-4 text-muted-foreground" />
            <span>{t("common.appearance")}</span>
            <span className="sr-only">{t("common.toggleTheme")}</span>
          </SidebarMenuButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={isMobile ? "top" : "right"}
          align="end"
          className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-2xl border border-white/10 bg-popover/95 p-1 backdrop-blur-xl"
        >
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            {t("common.light")}
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            {t("common.dark")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            {t("common.system")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  )
}

export const Appearance = () => {
  const { setTheme } = useTheme()
  const { t } = useI18n()

  return (
    <div className="flex items-center justify-center">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            data-testid="theme-button"
            variant="outline"
            size="icon"
            className="rounded-full border-white/10 bg-white/[0.03] backdrop-blur-xl hover:bg-white/[0.08]"
          >
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span className="sr-only">{t("common.toggleTheme")}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="rounded-2xl border border-white/10 bg-popover/95 p-1 backdrop-blur-xl"
        >
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            {t("common.light")}
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            {t("common.dark")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            {t("common.system")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
