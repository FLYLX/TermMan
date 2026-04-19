import { Languages } from "lucide-react"

import { useI18n } from "@/components/locale-provider"
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

export const SidebarLanguageSwitcher = () => {
  const { isMobile } = useSidebar()
  const { locale, setLocale, t } = useI18n()

  return (
    <SidebarMenuItem>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuButton
            tooltip={t("common.language")}
            data-testid="language-button"
          >
            <Languages className="size-4 text-muted-foreground" />
            <span>{t("common.language")}</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {locale.toUpperCase()}
            </span>
            <span className="sr-only">{t("common.toggleLanguage")}</span>
          </SidebarMenuButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={isMobile ? "top" : "right"}
          align="end"
          className="w-(--radix-dropdown-menu-trigger-width) min-w-44 rounded-2xl border border-white/10 bg-popover/95 p-1 backdrop-blur-xl"
        >
          <DropdownMenuItem onClick={() => setLocale("en")}>
            {t("common.english")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setLocale("zh")}>
            {t("common.chinese")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  )
}

export const LanguageSwitcher = () => {
  const { locale, setLocale, t } = useI18n()

  return (
    <div className="flex items-center justify-center">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            data-testid="language-button"
            variant="outline"
            size="sm"
            className="gap-2 rounded-full border-white/10 bg-white/[0.03] backdrop-blur-xl hover:bg-white/[0.08]"
          >
            <Languages className="size-4" />
            <span>{locale.toUpperCase()}</span>
            <span className="sr-only">{t("common.toggleLanguage")}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="rounded-2xl border border-white/10 bg-popover/95 p-1 backdrop-blur-xl"
        >
          <DropdownMenuItem onClick={() => setLocale("en")}>
            {t("common.english")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setLocale("zh")}>
            {t("common.chinese")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
