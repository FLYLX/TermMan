import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Bot, Check, Loader2, Moon, RefreshCw } from "lucide-react"

import {
  getItemRobotControllerStatus,
  getItemRobotControllerStatusQueryKey,
  type ItemRobotControllerStatusResponse,
  type RobotConversationControllerStatus,
} from "@/components/Robots/api"
import { useI18n } from "@/components/locale-provider"

type RobotControllerRow = {
  robot: ItemRobotControllerStatusResponse["robots"][number]
  controller: RobotConversationControllerStatus
}

function getRows(
  data: ItemRobotControllerStatusResponse | undefined,
): RobotControllerRow[] {
  if (!data) {
    return []
  }
  return data.robots
    .filter((robot) => robot.is_enabled && robot.allow_chat)
    .flatMap((robot) =>
      robot.conversation_controllers.map((controller) => ({
        robot,
        controller,
      })),
    )
    .sort(
      (left, right) =>
        Date.parse(right.controller.updated_at || "") -
        Date.parse(left.controller.updated_at || ""),
    )
}

function secondsRemaining(
  controller: RobotConversationControllerStatus | undefined,
  snapshotAtMs = 0,
  nowMs = Date.now(),
) {
  const reported = Number(controller?.seconds_remaining)
  if (Number.isFinite(reported)) {
    const elapsed = snapshotAtMs > 0 ? Math.max(0, (nowMs - snapshotAtMs) / 1000) : 0
    return Math.max(0, Math.ceil(reported - elapsed))
  }
  if (controller?.expires_at) {
    const expiresAt = Date.parse(controller.expires_at)
    if (Number.isFinite(expiresAt)) {
      return Math.max(0, Math.ceil((expiresAt - nowMs) / 1000))
    }
  }
  return 0
}

function isProcessing(controller: RobotConversationControllerStatus | undefined) {
  return controller?.status === "processing" || Boolean(controller?.processing)
}

function isAwake(
  controller: RobotConversationControllerStatus | undefined,
  snapshotAtMs = 0,
  nowMs = Date.now(),
) {
  return Boolean(
    controller?.awake && secondsRemaining(controller, snapshotAtMs, nowMs) > 0,
  )
}

function hasActive(data: ItemRobotControllerStatusResponse | undefined) {
  return getRows(data).some(
    ({ controller }) => isProcessing(controller) || isAwake(controller),
  )
}

function formatCountdown(seconds: number | null | undefined) {
  const safe = Math.max(0, Math.ceil(Number(seconds || 0)))
  if (safe < 60) {
    return `${safe}s`
  }
  const minutes = Math.floor(safe / 60)
  const rest = safe % 60
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}

function CountdownRing({
  seconds,
  totalSeconds,
}: {
  seconds: number | null | undefined
  totalSeconds: number | null | undefined
}) {
  const safeSeconds = Math.max(0, Math.ceil(Number(seconds || 0)))
  const safeTotal = Math.max(1, Math.ceil(Number(totalSeconds || safeSeconds || 1)))
  const progress = Math.min(1, safeSeconds / safeTotal)
  const radius = 7
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - progress)
  return (
    <span className="relative inline-flex size-6 shrink-0 items-center justify-center" aria-hidden="true">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="absolute inset-0 -rotate-90">
        <circle cx="10" cy="10" r={radius} fill="none" strokeWidth="2.2" className="stroke-current opacity-20" />
        <circle
          cx="10"
          cy="10"
          r={radius}
          fill="none"
          strokeWidth="2.2"
          strokeLinecap="round"
          className="stroke-current transition-[stroke-dashoffset] duration-700 ease-linear"
          style={{ strokeDasharray: circumference, strokeDashoffset: dashOffset }}
        />
      </svg>
      <span className="font-mono text-[9px] leading-none">{safeSeconds}</span>
    </span>
  )
}

function conversationLabel(controller: RobotConversationControllerStatus) {
  return (
    controller.conversation_key ||
    `${controller.conversation_type}:${controller.conversation_id}`
  )
}

export function RobotConversationDebugPanel({ itemId }: { itemId: string }) {
  const { t } = useI18n()
  const { data, dataUpdatedAt, isFetching } = useQuery({
    queryKey: getItemRobotControllerStatusQueryKey(itemId),
    queryFn: () => getItemRobotControllerStatus(itemId),
    refetchInterval: (query) => {
      if (query.state.error) {
        return 10_000
      }
      const d = query.state.data as ItemRobotControllerStatusResponse | undefined
      if (!d || d.count === 0) {
        return 15_000
      }
      return hasActive(d) ? 2_500 : 10_000
    },
    retry: false,
  })

  const [nowMs, setNowMs] = useState(() => Date.now())
  const active = hasActive(data)
  useEffect(() => {
    setNowMs(Date.now())
    if (!active) {
      return
    }
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])

  const rows = getRows(data)

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/70 text-xs text-slate-300">
      <div className="flex h-9 items-center justify-between border-b border-zinc-800 px-3">
        <div className="flex min-w-0 items-center gap-2 font-medium text-slate-200">
          <Bot className="size-3.5 shrink-0 text-cyan-300" />
          <span className="truncate">{t("items.detail.qqConversationDebug")}</span>
        </div>
        {isFetching ? <RefreshCw className="size-3 animate-spin text-slate-500" /> : null}
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-2 font-mono text-[11px] text-slate-500">
          {t("items.detail.qqNoConversations")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] table-fixed border-collapse text-left font-mono text-[11px]">
            <thead className="bg-zinc-900/80 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <tr>
                <th className="w-[9rem] px-3 py-2 font-medium">{t("robots.pageTitle")}</th>
                <th className="px-3 py-2 font-medium">{t("items.detail.qqConversation")}</th>
                <th className="w-[7rem] px-3 py-2 font-medium">{t("common.status")}</th>
                <th className="w-[8rem] px-3 py-2 font-medium">{t("items.detail.qqCountdown")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ robot, controller }) => {
                const processing = isProcessing(controller)
                const awake = isAwake(controller, dataUpdatedAt, nowMs)
                const remaining = secondsRemaining(controller, dataUpdatedAt, nowMs)
                const statusLabel = processing
                  ? t("items.detail.qqProcessing")
                  : awake
                    ? t("items.detail.qqAwake")
                    : t("items.detail.qqSleeping")
                const statusClass = processing
                  ? "bg-cyan-500/15 text-cyan-300"
                  : awake
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-slate-700/70 text-slate-300"
                return (
                  <tr
                    key={`${robot.robot_id}:${controller.conversation_key}`}
                    className="border-t border-zinc-900/90"
                  >
                    <td className="truncate px-3 py-2 text-slate-300">{robot.robot_name}</td>
                    <td className="truncate px-3 py-2 text-slate-400">
                      {conversationLabel(controller)}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex h-6 min-w-20 items-center justify-center rounded-full px-2 font-sans text-[11px] font-medium ${statusClass}`}>
                        {processing ? (
                          <Loader2 className="mr-1 size-3 animate-spin" />
                        ) : awake ? (
                          <Check className="mr-1 size-3" />
                        ) : (
                          <Moon className="mr-1 size-3" />
                        )}
                        {statusLabel}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-400">
                      <span className="inline-flex h-6 items-center gap-1.5">
                        {awake ? (
                          <CountdownRing
                            seconds={remaining}
                            totalSeconds={robot.reply_context_window_seconds}
                          />
                        ) : processing ? (
                          <Loader2 className="size-3 animate-spin text-cyan-300" />
                        ) : (
                          <Moon className="size-3 text-slate-500" />
                        )}
                        <span>
                          {awake ? formatCountdown(remaining) : processing ? "—" : "0s"}
                        </span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
