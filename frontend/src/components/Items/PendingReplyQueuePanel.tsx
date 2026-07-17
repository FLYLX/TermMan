import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Globe2,
  ListTodo,
  Loader2,
  MessageCircle,
  Monitor,
  RefreshCw,
  Send,
  Trash2,
  XCircle,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import {
  PENDING_REPLY_QUEUE_EVENT,
  type PendingReplyDestination,
  type PendingReplyEntry,
  PendingReplyService,
  type PendingReplyWorkflow,
} from "@/services/pending-replies"

interface PendingReplyQueuePanelProps {
  itemId: string
}

const COPY = {
  queueTitle: "\u4efb\u52a1\u961f\u5217",
  empty: "\u6682\u65e0\u4efb\u52a1",
  processing: "\u5904\u7406\u4e2d",
  waiting: "\u7b49\u5f85\u4e8b\u4ef6",
  ready: "\u5f85\u53d1\u9001",
  sending: "\u53d1\u9001\u4e2d",
  failed: "\u5931\u8d25",
  pending: "\u5f85\u5904\u7406",
  server: "\u670d\u52a1\u5668",
  web: "\u7f51\u9875",
  multiple: "\u591a\u76ee\u6807",
  targets: "\u56de\u590d\u76ee\u6807",
  progress: "\u6700\u65b0\u8fdb\u5ea6",
  workflow: "\u4efb\u52a1\u6d41\u7a0b",
  deleteSuccess: "\u4efb\u52a1\u5df2\u5220\u9664",
  deleteFailed: "\u5220\u9664\u4efb\u52a1\u5931\u8d25",
  sentTo: "\u5df2\u53d1\u9001\u5230",
  sendFailed:
    "\u53d1\u9001\u5931\u8d25\uff0c\u5931\u8d25\u76ee\u6807\u5df2\u4fdd\u7559",
  missingRequest: "\u672a\u8bb0\u5f55\u8bf7\u6c42\u5185\u5bb9",
  awaiting: "\u7b49\u5f85",
  sendComplete: "\u53d1\u9001\u5e76\u5b8c\u6210",
  delete: "\u5220\u9664",
  deleteConfirm:
    "\u5220\u8fd9\u6761\u4efb\u52a1\u53ca\u5168\u90e8\u56de\u590d\u76ee\u6807\uff1f",
  sendTo: "\u53d1\u9001\u5230",
  placeholder: "\u8f93\u5165\u6700\u7ec8\u6c47\u62a5\u5185\u5bb9",
  cancel: "\u53d6\u6d88",
  loadFailed: "\u4efb\u52a1\u961f\u5217\u52a0\u8f7d\u5931\u8d25",
  retry: "\u91cd\u8bd5",
} as const

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleTimeString("zh-CN", { hour12: false })
}

function statusLabel(status: string): string {
  switch (status) {
    case "working":
      return COPY.processing
    case "waiting":
      return COPY.waiting
    case "ready":
      return COPY.ready
    case "sending":
      return COPY.sending
    case "failed":
      return COPY.failed
    default:
      return COPY.pending
  }
}

function destinationLabel(type: string): string {
  switch (type) {
    case "qq":
      return "QQ"
    case "terminal":
      return COPY.server
    case "web":
      return COPY.web
    case "multiple":
      return COPY.multiple
    default:
      return type
  }
}

function DestinationIcon({ type }: { type: string }) {
  switch (type) {
    case "qq":
      return <MessageCircle className="size-3.5 text-cyan-300" />
    case "terminal":
      return <Monitor className="size-3.5 text-emerald-300" />
    default:
      return <Globe2 className="size-3.5 text-blue-300" />
  }
}

function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="size-3.5 text-emerald-400" />
    case "failed":
      return <XCircle className="size-3.5 text-red-400" />
    case "running":
      return <Loader2 className="size-3.5 animate-spin text-cyan-300" />
    case "waiting":
      return <Clock3 className="size-3.5 text-amber-300" />
    default:
      return <Circle className="size-3.5 text-slate-600" />
  }
}

function getDestinations(entry: PendingReplyEntry): PendingReplyDestination[] {
  if (entry.destinations?.length) return entry.destinations
  return [
    {
      id: entry.id,
      type: entry.destination_type,
      label: entry.destination_label,
      requester: entry.requester,
      status: entry.status,
      last_error: entry.last_error,
    },
  ]
}

export function PendingReplyQueuePanel({
  itemId,
}: PendingReplyQueuePanelProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [expandedEntries, setExpandedEntries] = useState<Set<string>>(new Set())
  const [sendingEntry, setSendingEntry] = useState<PendingReplyEntry | null>(
    null,
  )
  const [replyContent, setReplyContent] = useState("")

  const query = useQuery({
    queryKey: ["pending-replies", itemId],
    queryFn: () => PendingReplyService.list(itemId),
    refetchInterval: open ? 5_000 : 15_000,
    refetchOnWindowFocus: true,
  })
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["pending-replies", itemId] })

  useEffect(() => {
    const handleQueueChanged = (event: Event) => {
      const changedItemId = (event as CustomEvent<{ itemId?: string }>).detail
        ?.itemId
      if (changedItemId === itemId) {
        void queryClient.invalidateQueries({
          queryKey: ["pending-replies", itemId],
        })
      }
    }
    window.addEventListener(PENDING_REPLY_QUEUE_EVENT, handleQueueChanged)
    return () =>
      window.removeEventListener(PENDING_REPLY_QUEUE_EVENT, handleQueueChanged)
  }, [itemId, queryClient])

  const deleteMutation = useMutation({
    mutationFn: (entryId: string) =>
      PendingReplyService.delete(itemId, entryId),
    onSuccess: () => {
      showSuccessToast(COPY.deleteSuccess)
      void refresh()
    },
    onError: () => showErrorToast(COPY.deleteFailed),
  })

  const sendMutation = useMutation({
    mutationFn: ({ entryId, content }: { entryId: string; content: string }) =>
      PendingReplyService.send(itemId, entryId, content),
    onSuccess: (result) => {
      showSuccessToast(`${COPY.sentTo} ${result.destination}`)
      setSendingEntry(null)
      setReplyContent("")
      void refresh()
    },
    onError: () => showErrorToast(COPY.sendFailed),
  })

  const entries = query.data?.items ?? []
  const firstSummary = entries[0]?.request_summary || ""

  return (
    <div className="shrink-0 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/70 text-xs text-slate-300">
      <div className="flex h-10 items-center justify-between gap-2 px-3">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <ChevronRight
            className={`size-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-90" : ""}`}
          />
          <ListTodo className="size-3.5 shrink-0 text-cyan-300" />
          <span className="truncate font-medium text-slate-200">
            {COPY.queueTitle}
          </span>
          <Badge
            variant="outline"
            className="h-5 border-zinc-700 bg-zinc-900 px-1.5 font-mono text-[10px] text-slate-300"
          >
            {entries.length}
          </Badge>
          {firstSummary ? (
            <span className="hidden truncate text-[11px] text-slate-500 sm:inline">
              {firstSummary}
            </span>
          ) : null}
        </button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-slate-400 hover:bg-zinc-800 hover:text-slate-100"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          title={COPY.retry}
        >
          <RefreshCw
            className={`size-3.5 ${query.isFetching ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      {open ? (
        <div className="max-h-[28rem] overflow-y-auto border-t border-zinc-800 px-3 py-2">
          {query.isError ? (
            <div className="flex items-center justify-between gap-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-red-300">
              <span className="flex min-w-0 items-center gap-2">
                <AlertCircle className="size-4 shrink-0" />
                <span className="truncate">{COPY.loadFailed}</span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void query.refetch()}
              >
                {COPY.retry}
              </Button>
            </div>
          ) : entries.length === 0 ? (
            <div className="rounded-md border border-dashed border-zinc-800 bg-zinc-900/40 px-3 py-3 text-center text-slate-500">
              {query.isPending ? (
                <Loader2 className="mx-auto size-4 animate-spin" />
              ) : (
                COPY.empty
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {entries.map((entry) => {
                const expanded = expandedEntries.has(entry.id)
                const destinations = getDestinations(entry)
                const steps: NonNullable<PendingReplyWorkflow["steps"]> =
                  entry.workflow?.steps ??
                  entry.task_plan.map((title) => ({
                    title,
                    status: "pending",
                  }))
                return (
                  <div
                    key={entry.id}
                    className="overflow-hidden rounded-md border border-zinc-800 bg-zinc-900/60"
                  >
                    <div className="flex items-start gap-2 px-3 py-2.5">
                      <button
                        type="button"
                        className="flex min-w-0 flex-1 items-start gap-2 text-left"
                        onClick={() =>
                          setExpandedEntries((current) => {
                            const next = new Set(current)
                            if (next.has(entry.id)) next.delete(entry.id)
                            else next.add(entry.id)
                            return next
                          })
                        }
                      >
                        <ChevronRight
                          className={`mt-0.5 size-3.5 shrink-0 text-slate-500 transition-transform ${expanded ? "rotate-90" : ""}`}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <Badge
                              variant="secondary"
                              className="h-5 bg-zinc-800 text-[10px] text-slate-300"
                            >
                              {statusLabel(entry.status)}
                            </Badge>
                            <Badge
                              variant="outline"
                              className="h-5 border-zinc-700 text-[10px] text-slate-400"
                            >
                              {destinations.length} {COPY.targets}
                            </Badge>
                            <span className="font-mono text-[10px] text-slate-500">
                              {formatTime(entry.updated_at)}
                            </span>
                          </span>
                          <span className="mt-1 block truncate text-xs font-medium text-slate-200">
                            {entry.request_summary || COPY.missingRequest}
                          </span>
                          {entry.workflow?.latest_progress ? (
                            <span className="mt-1 block truncate text-[11px] text-slate-500">
                              {entry.workflow.latest_progress}
                            </span>
                          ) : null}
                        </span>
                      </button>
                      <div className="flex shrink-0 gap-1">
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-7 text-slate-400 hover:bg-zinc-800 hover:text-cyan-200"
                          title={COPY.sendComplete}
                          onClick={() => {
                            setSendingEntry(entry)
                            setReplyContent("")
                          }}
                        >
                          <Send className="size-3.5" />
                        </Button>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-7 text-slate-500 hover:bg-red-500/10 hover:text-red-300"
                          title={COPY.delete}
                          disabled={deleteMutation.isPending}
                          onClick={() => {
                            if (window.confirm(COPY.deleteConfirm))
                              deleteMutation.mutate(entry.id)
                          }}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </div>

                    {expanded ? (
                      <div className="space-y-3 border-t border-zinc-800 px-3 py-3">
                        <section>
                          <div className="mb-1.5 text-[10px] font-medium uppercase text-slate-500">
                            {COPY.targets}
                          </div>
                          <div className="grid gap-1.5 md:grid-cols-2">
                            {destinations.map((destination) => (
                              <div
                                key={destination.id}
                                className="flex min-w-0 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/60 px-2.5 py-2"
                              >
                                <DestinationIcon type={destination.type} />
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-[11px] text-slate-300">
                                    {destination.label}
                                  </span>
                                  <span className="block truncate text-[10px] text-slate-600">
                                    {destination.requester ||
                                      destinationLabel(destination.type)}
                                  </span>
                                </span>
                                <span className="shrink-0 text-[10px] text-slate-500">
                                  {statusLabel(destination.status)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </section>

                        {steps.length ? (
                          <section>
                            <div className="mb-1.5 text-[10px] font-medium uppercase text-slate-500">
                              {COPY.workflow}
                            </div>
                            <div className="space-y-1">
                              {steps.map((step, index) => (
                                <div
                                  key={step.step_id || `${entry.id}:${index}`}
                                  className="flex items-start gap-2 rounded-md px-1.5 py-1.5"
                                >
                                  <StepIcon status={step.status} />
                                  <span className="min-w-0 flex-1">
                                    <span className="block text-[11px] text-slate-300">
                                      {index + 1}. {step.title}
                                    </span>
                                    {step.last_error || step.evidence ? (
                                      <span
                                        className={`mt-0.5 block line-clamp-2 text-[10px] ${step.last_error ? "text-red-300" : "text-slate-600"}`}
                                      >
                                        {step.last_error || step.evidence}
                                      </span>
                                    ) : null}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </section>
                        ) : null}

                        {entry.awaiting_key ? (
                          <div className="font-mono text-[10px] text-amber-300">
                            {COPY.awaiting}: {entry.awaiting_kind}:
                            {entry.awaiting_key}
                          </div>
                        ) : null}
                        {entry.last_error ? (
                          <div className="text-[11px] text-red-300">
                            {entry.last_error}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ) : null}

      <Dialog
        open={Boolean(sendingEntry)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setSendingEntry(null)
            setReplyContent("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {COPY.sendTo}{" "}
              {sendingEntry ? getDestinations(sendingEntry).length : 0}{" "}
              {COPY.targets}
            </DialogTitle>
          </DialogHeader>
          <Textarea
            rows={5}
            value={replyContent}
            onChange={(event) => setReplyContent(event.target.value)}
            placeholder={COPY.placeholder}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSendingEntry(null)}>
              {COPY.cancel}
            </Button>
            <Button
              disabled={!replyContent.trim() || sendMutation.isPending}
              onClick={() => {
                if (sendingEntry) {
                  sendMutation.mutate({
                    entryId: sendingEntry.id,
                    content: replyContent.trim(),
                  })
                }
              }}
            >
              {sendMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Send className="size-4" />
              )}
              {COPY.sendComplete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
