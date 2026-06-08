import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { Search, Wifi, WifiOff } from "lucide-react"
import { Suspense, useEffect, useState } from "react"

import { ItemsService } from "@/client"
import AddItem from "@/components/Items/AddItem"
import { ItemActionsMenu } from "@/components/Items/ItemActionsMenu"
import {
  type DaemonGroup,
  groupItemsByDaemon,
  type TerminalItem,
} from "@/components/Items/terminal-utils"
import { useI18n } from "@/components/locale-provider"
import PendingItems from "@/components/Pending/PendingItems"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { getStatusLabel } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const LIST_PAGE_SIZE = 10

type ItemsResponse = {
  data: TerminalItem[]
  count: number
}

function getItemsQueryOptions() {
  return {
    queryFn: () => ItemsService.readItems({ skip: 0, limit: 100 }),
    queryKey: ["items"],
  }
}

function TerminalStateBadge({ status }: { status?: string | null }) {
  const { locale } = useI18n()
  const label = getStatusLabel(locale, status || undefined)

  switch (status) {
    case "running":
      return (
        <Badge className="h-6 border-emerald-500/30 bg-emerald-500/10 px-2 text-[11px] text-emerald-700 dark:text-emerald-300">
          {label}
        </Badge>
      )
    case "starting":
      return (
        <Badge className="h-6 border-amber-500/30 bg-amber-500/10 px-2 text-[11px] text-amber-700 dark:text-amber-300">
          {label}
        </Badge>
      )
    case "stopping":
      return (
        <Badge className="h-6 border-orange-500/30 bg-orange-500/10 px-2 text-[11px] text-orange-700 dark:text-orange-300">
          {label}
        </Badge>
      )
    case "error":
      return (
        <Badge className="h-6 border-rose-500/30 bg-rose-500/10 px-2 text-[11px] text-rose-700 dark:text-rose-300">
          {label}
        </Badge>
      )
    default:
      return (
        <Badge className="h-6 border-border bg-background px-2 text-[11px] text-muted-foreground dark:bg-white/5 dark:text-slate-200">
          {label}
        </Badge>
      )
  }
}

function TerminalCard({
  item,
  onOpen,
}: {
  item: TerminalItem
  onOpen: (itemId: string) => void
}) {
  const { locale } = useI18n()

  const copy =
    locale === "zh"
      ? {
          command: "命令",
          waitingCommand: "等待启动命令",
          cwd: "工作目录",
        }
      : {
          command: "Command",
          waitingCommand: "waiting for boot command",
          cwd: "Working directory",
        }

  return (
    <div
      role="button"
      tabIndex={0}
      className="group w-full text-left"
      onClick={() => onOpen(item.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onOpen(item.id)
        }
      }}
    >
      <div className="rounded-2xl border border-border/70 bg-card p-1 shadow-sm transition duration-200 hover:border-primary/30 hover:shadow-md">
        <div className="overflow-hidden rounded-[14px] border border-slate-200/80 bg-[#f7fcf8] text-slate-900 dark:border-slate-800/90 dark:bg-slate-950 dark:text-slate-100">
          <div className="flex min-w-0 flex-col gap-2 px-3 py-2 lg:flex-row lg:items-center lg:gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex shrink-0 items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-[#ff5f57]" />
                <span className="size-2.5 rounded-full bg-[#febc2e]" />
                <span className="size-2.5 rounded-full bg-[#28c840]" />
              </div>
              <div className="min-w-0 truncate rounded-md border border-slate-200/80 bg-white px-2 py-1 font-mono text-[11px] text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300">
                {item.title}
              </div>
              <TerminalStateBadge status={item.status} />
            </div>

            <div className="hidden h-5 w-px shrink-0 bg-slate-200/90 lg:block dark:bg-white/10" />

            <div className="flex min-w-0 flex-1 flex-col gap-2 lg:flex-row lg:items-center lg:gap-3">
              <div className="flex min-w-0 items-center gap-2 rounded-lg border border-slate-200/80 bg-white px-2.5 py-1.5 dark:border-white/8 dark:bg-white/5 lg:flex-[1.35]">
                <div className="shrink-0 text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                  {copy.command}
                </div>
                <div className="min-w-0 truncate font-mono text-xs text-slate-800 dark:text-slate-100">
                  <span className="mr-1 text-slate-400 dark:text-slate-500">
                    $
                  </span>
                  <span>{item.command || copy.waitingCommand}</span>
                </div>
              </div>

              <div className="flex min-w-0 items-center gap-2 rounded-lg border border-slate-200/80 bg-white px-2.5 py-1.5 dark:border-white/8 dark:bg-white/4 lg:flex-1">
                <div className="shrink-0 text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                  {copy.cwd}
                </div>
                <div className="min-w-0 truncate font-mono text-xs text-slate-800 dark:text-slate-100">
                  {item.working_directory || "~"}
                </div>
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-end">
              <ItemActionsMenu item={item} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function DaemonSection({
  group,
  items,
  onOpenTerminal,
}: {
  group: DaemonGroup
  items: TerminalItem[]
  onOpenTerminal: (itemId: string) => void
}) {
  const { locale } = useI18n()
  const [visibleCount, setVisibleCount] = useState(LIST_PAGE_SIZE)

  useEffect(() => {
    setVisibleCount(LIST_PAGE_SIZE)
  }, [group.key])

  const visibleItems = group.items.slice(0, visibleCount)
  const remainingCount = Math.max(group.items.length - visibleItems.length, 0)
  const nextCount = Math.min(LIST_PAGE_SIZE, remainingCount)

  const copy =
    locale === "zh"
      ? {
          terminals: "终端",
          online: "在线",
          offline: "离线",
          addTerminal: group.isConfigured ? "添加终端" : "手动新建",
          unassigned: "未绑定 Daemon",
        }
      : {
          terminals: "terminals",
          online: "Online",
          offline: "Offline",
          addTerminal: group.isConfigured ? "Add Terminal" : "Create Manually",
          unassigned: "Unassigned daemon",
        }

  return (
    <section className="rounded-3xl border bg-card shadow-sm">
      <div className="border-b px-4 py-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate font-mono text-base font-semibold tracking-tight">
              {group.isConfigured ? group.label : copy.unassigned}
            </h2>
            <Badge
              variant="outline"
              className={cn(
                "h-6 px-2 text-[11px]",
                group.daemonOnline
                  ? "border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
                  : "border-rose-500/30 text-rose-600 dark:text-rose-400",
              )}
            >
              {group.daemonOnline ? (
                <Wifi className="mr-1 size-3.5" />
              ) : (
                <WifiOff className="mr-1 size-3.5" />
              )}
              {group.daemonOnline ? copy.online : copy.offline}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {group.items.length} {copy.terminals}
            </span>
          </div>

          <AddItem
            items={items}
            initialDaemonKey={group.isConfigured ? group.key : undefined}
            triggerLabel={copy.addTerminal}
            triggerVariant="outline"
          />
        </div>
      </div>

      <div className="grid gap-2 p-3">
        {visibleItems.map((item) => (
          <TerminalCard key={item.id} item={item} onOpen={onOpenTerminal} />
        ))}
        {remainingCount > 0 ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="justify-center"
            onClick={() =>
              setVisibleCount((current) => current + LIST_PAGE_SIZE)
            }
          >
            {locale === "zh"
              ? `再显示 ${nextCount} 条`
              : `Show ${nextCount} more`}
          </Button>
        ) : null}
      </div>
    </section>
  )
}

function ItemsPageContent() {
  const navigate = useNavigate()
  const { data } = useSuspenseQuery(getItemsQueryOptions())
  const { locale, t } = useI18n()

  const itemsData = ((data as ItemsResponse)?.data || []) as TerminalItem[]
  const daemonGroups = groupItemsByDaemon(itemsData)

  const copy =
    locale === "zh"
      ? {
          noTerminals: "还没有终端",
          noTerminalsHint:
            "先新建一个终端，再按 Daemon 继续分组使用。",
        }
      : {
          noTerminals: "No terminals yet",
          noTerminalsHint:
            "Create the first terminal, then keep grouping by daemon.",
        }

  const openTerminal = (itemId: string) => {
    void navigate({
      to: "/items/$itemId",
      params: { itemId },
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-3xl border bg-card px-4 py-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("items.pageTitle")}
          </h1>
          <AddItem items={itemsData} triggerLabel={t("items.add")} />
        </div>
      </section>

      {itemsData.length === 0 ? (
        <div className="rounded-3xl border border-dashed bg-card/60 px-8 py-10 text-center shadow-sm">
          <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-full border bg-muted/30">
            <Search className="size-5 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-semibold">{copy.noTerminals}</h2>
          <p className="mx-auto mt-1 max-w-xl text-sm text-muted-foreground">
            {copy.noTerminalsHint}
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {daemonGroups.map((group) => (
            <DaemonSection
              key={group.key}
              group={group}
              items={itemsData}
              onOpenTerminal={openTerminal}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/_layout/items/")({
  component: Items,
  head: () => ({
    meta: [
      {
        title: "Terminals - TermMan",
      },
    ],
  }),
})

function Items() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemsPageContent />
    </Suspense>
  )
}
