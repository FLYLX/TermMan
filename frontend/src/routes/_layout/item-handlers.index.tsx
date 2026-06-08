import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  BookOpen,
  Link2,
  Search,
  Server,
  Sparkles,
  Terminal,
} from "lucide-react"
import { Suspense, useState } from "react"

import { type ItemHandlerPublic, ItemHandlersService } from "@/client"
import AddItemHandler from "@/components/ItemHandlers/AddItemHandler"
import {
  getItemHandlerLlmStatusQueryKey,
  type ItemHandlerLlmStatusItem,
  listItemHandlerLlmStatuses,
} from "@/components/ItemHandlers/api"
import { ItemHandlerActionsMenu } from "@/components/ItemHandlers/ItemHandlerActionsMenu"
import { useI18n } from "@/components/locale-provider"
import PendingItems from "@/components/Pending/PendingItems"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const LIST_PAGE_SIZE = 10

type ItemHandlerWithSummary = ItemHandlerPublic & {
  item_count?: number
  user_count?: number
  enabled_knowledge_files?: string[]
}

function getItemHandlersQueryOptions() {
  return {
    queryFn: async () => {
      const itemHandlers = await ItemHandlersService.readItemHandlers({
        skip: 0,
        limit: 100,
      })

      return itemHandlers as ItemHandlerWithSummary[]
    },
    queryKey: ["itemHandlers"],
    staleTime: 0,
    cacheTime: 30000,
  }
}

function StatChip({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Terminal
  label: string
  value: number
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-background/70 px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <span className="whitespace-nowrap">{label}</span>
      </div>
      <span className="ml-auto shrink-0 text-sm font-semibold tracking-tight">
        {value}
      </span>
    </div>
  )
}

function HandlerLlmBadge({
  llmStatus,
}: {
  llmStatus?: ItemHandlerLlmStatusItem
}) {
  const { locale } = useI18n()

  const copy =
    locale === "zh"
      ? {
          connected: "LLM 在线",
          error: "LLM 异常",
          notConfigured: "LLM 未配置",
          checking: "LLM 检测中",
        }
      : {
          connected: "LLM Online",
          error: "LLM Error",
          notConfigured: "LLM Unset",
          checking: "LLM Checking",
        }

  if (!llmStatus) {
    return (
      <Badge
        variant="outline"
        className="h-6 whitespace-nowrap border-border px-2 text-[11px] text-muted-foreground"
      >
        {copy.checking}
      </Badge>
    )
  }

  if (llmStatus.status === "connected") {
    return (
      <Badge
        variant="outline"
        title={llmStatus.message || undefined}
        className="h-6 whitespace-nowrap border-emerald-500/30 bg-emerald-500/10 px-2 text-[11px] text-emerald-700 dark:text-emerald-300"
      >
        {copy.connected}
      </Badge>
    )
  }

  if (llmStatus.status === "not_configured") {
    return (
      <Badge
        variant="outline"
        title={llmStatus.message || undefined}
        className="h-6 whitespace-nowrap border-amber-500/30 bg-amber-500/10 px-2 text-[11px] text-amber-700 dark:text-amber-300"
      >
        {copy.notConfigured}
      </Badge>
    )
  }

  return (
    <Badge
      variant="outline"
      title={llmStatus.message || undefined}
      className="h-6 whitespace-nowrap border-rose-500/30 bg-rose-500/10 px-2 text-[11px] text-rose-700 dark:text-rose-300"
    >
      {copy.error}
    </Badge>
  )
}

function HandlerCard({
  handler,
  llmStatus,
  onOpen,
}: {
  handler: ItemHandlerWithSummary
  llmStatus?: ItemHandlerLlmStatusItem
  onOpen: (handlerId: string) => void
}) {
  const { locale } = useI18n()

  const knowledgeCount = (
    ((handler as Record<string, unknown>).enabled_knowledge_files ??
      []) as string[]
  ).length
  const terminalCount = handler.item_count ?? 0
  const skillCount = (handler.enabled_skills ?? []).length
  const mcpCount = (
    ((handler as Record<string, unknown>).enabled_mcp_servers ??
      []) as unknown[]
  ).length

  const copy =
    locale === "zh"
      ? {
          model: "模型",
          api: "API",
          terminals: "终端",
          skills: "技能",
          knowledge: "知识库",
          mcp: "MCP",
          noModel: "未配置模型",
          noApi: "未配置 API",
          attachedTerminals: "已连接终端",
          noTerminals: "当前还没有连接任何终端",
          terminalSummary: "进入详情后按需加载终端列表。",
        }
      : {
          model: "Model",
          api: "API",
          terminals: "Terms",
          skills: "Skills",
          knowledge: "Knowledge",
          mcp: "MCP",
          noModel: "No model configured",
          noApi: "No API configured",
          attachedTerminals: "Attached terminals",
          noTerminals: "No terminals attached yet",
          terminalSummary: "Open details to load the terminal list on demand.",
        }

  return (
    <div
      role="button"
      tabIndex={0}
      className="group flex h-full w-full text-left"
      onClick={() => onOpen(handler.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onOpen(handler.id)
        }
      }}
    >
      <div className="flex h-full w-full rounded-[20px] border bg-card p-1 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
        <div className="flex h-full w-full flex-col overflow-hidden rounded-[16px] border bg-card">
          <div className="border-b px-3 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 space-y-1.5">
                <h2 className="truncate text-base font-semibold tracking-tight">
                  {handler.name}
                </h2>
                <div className="flex flex-wrap items-center gap-1.5">
                  <HandlerLlmBadge llmStatus={llmStatus} />
                  <Badge
                    variant="outline"
                    className="h-6 whitespace-nowrap px-2 text-[11px]"
                  >
                    {terminalCount} {copy.terminals}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="h-6 whitespace-nowrap px-2 text-[11px]"
                  >
                    {knowledgeCount} {copy.knowledge}
                  </Badge>
                </div>
              </div>

              <ItemHandlerActionsMenu itemHandler={handler} />
            </div>
          </div>

          <div className="flex flex-1 flex-col space-y-2.5 p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-background/70 px-2.5 py-2">
                <div className="shrink-0 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  {copy.model}
                </div>
                <div className="min-w-0 truncate font-mono text-xs">
                  {handler.model || copy.noModel}
                </div>
              </div>

              <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-background/70 px-2.5 py-2">
                <div className="shrink-0 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  {copy.api}
                </div>
                <div className="min-w-0 truncate font-mono text-xs">
                  {handler.api_url || copy.noApi}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
              <StatChip
                icon={Terminal}
                label={copy.terminals}
                value={terminalCount}
              />
              <StatChip
                icon={Sparkles}
                label={copy.skills}
                value={skillCount}
              />
              <StatChip
                icon={BookOpen}
                label={copy.knowledge}
                value={knowledgeCount}
              />
              <StatChip icon={Server} label={copy.mcp} value={mcpCount} />
            </div>

            <div className="mt-auto min-h-24 rounded-lg border bg-background/60 px-2.5 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                <Link2 className="size-3.5" />
                <span className="whitespace-nowrap">
                  {copy.attachedTerminals}
                </span>
              </div>

              {terminalCount === 0 ? (
                <div className="mt-2 text-xs text-muted-foreground">
                  {copy.noTerminals}
                </div>
              ) : (
                <div className="mt-2 rounded-lg border bg-muted/30 px-2.5 py-2 text-xs text-muted-foreground">
                  {terminalCount} {copy.terminals} · {copy.terminalSummary}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ItemHandlersContent() {
  const navigate = useNavigate()
  const { locale, t } = useI18n()
  const [visibleCount, setVisibleCount] = useState(LIST_PAGE_SIZE)
  const { data: itemHandlers } = useSuspenseQuery(getItemHandlersQueryOptions())
  const { data: llmStatusResponse } = useQuery({
    queryKey: getItemHandlerLlmStatusQueryKey(),
    queryFn: () => listItemHandlerLlmStatuses(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const llmStatusById = new Map(
    (llmStatusResponse?.data ?? []).map((item) => [item.item_handler_id, item]),
  )
  const visibleItemHandlers = itemHandlers.slice(0, visibleCount)
  const remainingCount = Math.max(
    itemHandlers.length - visibleItemHandlers.length,
    0,
  )
  const nextCount = Math.min(LIST_PAGE_SIZE, remainingCount)

  const copy =
    locale === "zh"
      ? {
          emptyTitle: "还没有 TermHandler",
          emptyDescription: "先创建一个 TermHandler，再把终端和知识接进来。",
        }
      : {
          emptyTitle: "No TermHandlers yet",
          emptyDescription:
            "Create a TermHandler first, then wire terminals and knowledge into it.",
        }

  const openHandler = (itemHandlerId: string) => {
    void navigate({
      to: "/item-handlers/$itemHandlerId",
      params: { itemHandlerId },
    })
  }

  if (itemHandlers.length === 0) {
    return (
      <div className="rounded-[30px] border border-dashed bg-card/60 px-8 py-14 text-center shadow-sm">
        <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-full border bg-muted/30">
          <Search className="size-7 text-muted-foreground" />
        </div>
        <h2 className="text-xl font-semibold">{copy.emptyTitle}</h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          {copy.emptyDescription}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-3xl border bg-card px-4 py-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("itemHandlers.pageTitle")}
          </h1>
          <AddItemHandler triggerLabel={t("itemHandlers.add")} />
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {visibleItemHandlers.map((handler) => (
          <HandlerCard
            key={handler.id}
            handler={handler}
            llmStatus={llmStatusById.get(handler.id)}
            onOpen={openHandler}
          />
        ))}
      </div>
      {remainingCount > 0 ? (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              setVisibleCount((current) => current + LIST_PAGE_SIZE)
            }
          >
            {locale === "zh"
              ? `再显示 ${nextCount} 条`
              : `Show ${nextCount} more`}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export const Route = createFileRoute("/_layout/item-handlers/")({
  component: ItemHandlers,
  head: () => ({
    meta: [
      {
        title: "TermHandlers - TermMan",
      },
    ],
  }),
})

function ItemHandlers() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemHandlersContent />
    </Suspense>
  )
}
