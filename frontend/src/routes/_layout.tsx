import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { Appearance } from "@/components/Common/Appearance"
import { Footer } from "@/components/Common/Footer"
import { LanguageSwitcher } from "@/components/Common/LanguageSwitcher"
import { useI18n } from "@/components/locale-provider"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const { t } = useI18n()

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-h-svh">
        <header className="sticky top-0 z-20 border-b bg-background/95">
          <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 md:px-6">
            <SidebarTrigger className="-ml-1 rounded-xl border bg-background text-muted-foreground hover:bg-muted" />
            <div className="hidden min-w-0 items-center gap-3 md:flex">
              <div className="h-8 w-px bg-border" />
              <div className="min-w-0">
                <p className="font-mono text-[10px] uppercase tracking-[0.34em] text-primary/75">
                  TermMan
                </p>
                <p className="truncate text-sm text-muted-foreground">
                  {t("brand.appDescription")}
                </p>
              </div>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <LanguageSwitcher />
              <Appearance />
            </div>
          </div>
        </header>
        <main className="flex-1 px-4 pb-6 pt-6 md:px-6 md:pb-8 md:pt-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <div className="mx-auto w-full max-w-7xl">
          <Footer />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
