import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, ListTodo, Loader2, Send, Trash2 } from "lucide-react"
import { useState } from "react"

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
  type PendingReplyEntry,
  PendingReplyService,
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
  deleteSuccess: "\u4efb\u52a1\u5df2\u5220\u9664",
  deleteFailed: "\u5220\u9664\u4efb\u52a1\u5931\u8d25",
  sentTo: "\u5df2\u53d1\u9001\u5230",
  sendFailed: "\u53d1\u9001\u5931\u8d25\uff0c\u4efb\u52a1\u5df2\u4fdd\u7559",
  missingRequest: "\u672a\u8bb0\u5f55\u8bf7\u6c42\u5185\u5bb9",
  destination: "\u76ee\u7684\u5730",
  plan: "\u8ba1\u5212",
  awaiting: "\u7b49\u5f85",
  current: "\u5f53\u524d",
  sendComplete: "\u53d1\u9001\u5e76\u5b8c\u6210",
  delete: "\u5220\u9664",
  deleteConfirm: "\u5220\u9664\u8fd9\u6761\u4efb\u52a1\uff1f",
  sendTo: "\u53d1\u9001\u5230",
  placeholder: "\u8f93\u5165\u6700\u7ec8\u6c47\u62a5\u5185\u5bb9",
  cancel: "\u53d6\u6d88",
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
    default:
      return type
  }
}

export function PendingReplyQueuePanel({
  itemId,
}: PendingReplyQueuePanelProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(true)
  const [sendingEntry, setSendingEntry] = useState<PendingReplyEntry | null>(
    null,
  )
  const [replyContent, setReplyContent] = useState("")

  const query = useQuery({
    queryKey: ["pending-replies", itemId],
    queryFn: () => PendingReplyService.list(itemId),
    refetchInterval: 5_000,
  })
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["pending-replies", itemId] })

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

  return (
    <div className="overflow-hidden rounded-lg border border-border/60 bg-card/80">
      <button
        type="button"
        className="flex h-10 w-full items-center justify-between gap-3 px-3 text-left text-sm"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <ListTodo className="size-4 shrink-0 text-cyan-500" />
          <span className="truncate font-medium">{COPY.queueTitle}</span>
          <Badge variant="outline">{entries.length}</Badge>
        </span>
        <span className="flex items-center gap-2">
          {query.isFetching ? (
            <Loader2 className="size-3 animate-spin" />
          ) : null}
          <ChevronRight
            className={`size-4 transition-transform ${open ? "rotate-90" : ""}`}
          />
        </span>
      </button>

      {open ? (
        <div className="max-h-[18rem] overflow-y-auto border-t border-border/60 p-2">
          {entries.length === 0 ? (
            <div className="py-5 text-center text-xs text-muted-foreground">
              {COPY.empty}
            </div>
          ) : (
            <div className="space-y-2">
              {entries.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded-md border border-border/50 bg-muted/20 p-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                        <Badge variant="secondary">
                          {statusLabel(entry.status)}
                        </Badge>
                        <Badge variant="outline">
                          {destinationLabel(entry.destination_type)}
                        </Badge>
                        <span className="truncate font-medium">
                          {entry.requester}
                        </span>
                      </div>
                      <p className="mt-1.5 line-clamp-2 text-xs leading-5">
                        {entry.request_summary || COPY.missingRequest}
                      </p>
                    </div>
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                      {formatTime(entry.updated_at)}
                    </span>
                  </div>

                  <div className="mt-2 space-y-1 border-t border-border/50 pt-2 text-[11px]">
                    <div className="flex gap-2">
                      <span className="shrink-0 text-muted-foreground">
                        {COPY.destination}
                      </span>
                      <span className="truncate">
                        {entry.destination_label}
                      </span>
                    </div>
                    {entry.task_plan.length > 0 ? (
                      <div className="flex gap-2">
                        <span className="shrink-0 text-muted-foreground">
                          {COPY.plan}
                        </span>
                        <span className="line-clamp-2">
                          {entry.task_plan.join(" -> ")}
                        </span>
                      </div>
                    ) : null}
                    {entry.awaiting_key ? (
                      <div className="flex gap-2">
                        <span className="shrink-0 text-muted-foreground">
                          {COPY.awaiting}
                        </span>
                        <span className="truncate font-mono">
                          {entry.awaiting_kind}:{entry.awaiting_key}
                        </span>
                      </div>
                    ) : null}
                    {entry.workflow?.current_step ? (
                      <div className="flex gap-2">
                        <span className="shrink-0 text-muted-foreground">
                          {COPY.current}
                        </span>
                        <span className="line-clamp-1">
                          {entry.workflow.current_step}
                        </span>
                      </div>
                    ) : null}
                    {entry.last_error ? (
                      <p className="text-red-500">{entry.last_error}</p>
                    ) : null}
                  </div>

                  <div className="mt-2 flex justify-end gap-1">
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-7"
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
                      className="size-7 text-red-500 hover:text-red-500"
                      title={COPY.delete}
                      disabled={deleteMutation.isPending}
                      onClick={() => {
                        if (window.confirm(COPY.deleteConfirm)) {
                          deleteMutation.mutate(entry.id)
                        }
                      }}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
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
              {COPY.sendTo} {sendingEntry?.destination_label}
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
