import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronRight,
  Copy,
  Plug,
  Send,
  Terminal,
  WifiOff,
} from "lucide-react"
import { useEffect, useMemo } from "react"

import {
  ApiError,
  type ItemPublic,
  type ItemsPublic,
  ItemsService,
} from "@/client"
import {
  createFallbackItem,
  getStoredItemSnapshot,
  saveItemSnapshot,
} from "@/components/Items/itemDetailSnapshots"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

function getItemQueryOptions(itemId: string) {
  return {
    queryFn: () => ItemsService.readItem({ id: itemId }),
    queryKey: ["items", "detail", itemId],
    refetchOnWindowFocus: false,
    retry: false,
  }
}

function getCachedItem(items: ItemsPublic | undefined, itemId: string) {
  return items?.data.find((item) => item.id === itemId)
}

function formatDate(value?: string | null) {
  if (!value) {
    return "N/A"
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function getErrorMessage(error: Error | null) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: string })?.detail
    if (detail) {
      return detail
    }
  }

  return error?.message || "Unable to load item details right now."
}

function CopyValue({ label, value }: { label: string; value?: string | null }) {
  const [copiedText, copy] = useCopyToClipboard()
  const displayValue = value || "N/A"
  const isCopied = copiedText === displayValue

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm">{displayValue}</span>
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={() => copy(displayValue)}
          >
            {isCopied ? (
              <Check className="size-3 text-green-500" />
            ) : (
              <Copy className="size-3" />
            )}
            <span className="sr-only">Copy {label}</span>
          </Button>
        )}
      </div>
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">{value || "N/A"}</span>
    </div>
  )
}

function getStatusBadge(status?: string) {
  switch (status) {
    case "running":
      return (
        <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
          Running
        </Badge>
      )
    case "starting":
      return (
        <Badge className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
          Starting
        </Badge>
      )
    case "stopping":
      return (
        <Badge className="border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400">
          Stopping
        </Badge>
      )
    case "stopped":
      return (
        <Badge variant="secondary">Stopped</Badge>
      )
    case "error":
      return (
        <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
          Error
        </Badge>
      )
    default:
      return <Badge variant="outline">Unknown</Badge>
  }
}

function ItemDetailPage({
  item,
  isLoading,
  isUsingFallback,
  message,
}: {
  item: ItemPublic
  isLoading: boolean
  isUsingFallback: boolean
  message?: string
}) {
  return (
    <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-6">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Link to="/items" className="hover:text-foreground">
            Items
          </Link>
          <ChevronRight className="size-4" />
          <span className="text-foreground">Terminal</span>
        </div>

        <div className="rounded-2xl border bg-card/85 px-5 py-5 shadow-sm">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex flex-col gap-4">
              <Button
                asChild
                variant="outline"
                size="sm"
                className="h-8 w-fit px-3"
              >
                <Link to="/items">
                  <ArrowLeft className="size-4" />
                  Back to items
                </Link>
              </Button>

              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <div className="flex size-12 items-center justify-center rounded-xl border bg-muted/40">
                  <Terminal className="size-6 text-muted-foreground" />
                </div>

                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="text-3xl font-bold tracking-tight">
                      {item.title}
                    </h1>
                    {getStatusBadge(item.status)}
                    {isUsingFallback && (
                      <Badge variant="secondary">Fallback Mode</Badge>
                    )}
                  </div>

                  <p className="max-w-3xl text-sm text-muted-foreground">
                    {item.description || "No description"}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {isUsingFallback && (
            <div className="mt-5 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm">
              <div className="flex items-center gap-2">
                <AlertCircle className="size-4 text-yellow-600 dark:text-yellow-400" />
                <span className="font-medium text-yellow-600 dark:text-yellow-400">
                  {message || "Rendering with cached or placeholder data"}
                </span>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold">Terminal</h2>
              <p className="text-sm text-muted-foreground">
                Real-time console output and command input
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {item.socket_connected ? (
                <>
                  <Badge variant="secondary">Realtime Console</Badge>
                  <Badge variant="secondary">History Reserved</Badge>
                </>
              ) : (
                <Badge variant="outline" className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
                  <WifiOff className="size-3 mr-1" />
                  Disconnected
                </Badge>
              )}
            </div>
          </div>

          <div className="rounded-2xl border bg-[#151515] p-4 shadow-inner">
            <div className="mb-3 flex items-center gap-2">
              <span className="size-3 rounded-full bg-red-400" />
              <span className="size-3 rounded-full bg-yellow-400" />
              <span className="size-3 rounded-full bg-green-400" />
              <span className="ml-2 font-mono text-xs tracking-wide text-slate-400">
                terminal
              </span>
            </div>

            {item.socket_connected ? (
              <>
                <div className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] px-4 py-3 font-mono text-[15px] leading-[1.45] tracking-[0.01em]">
                  <div className="text-lime-400">[System] Terminal connected. Waiting for output...</div>
                </div>

                <div className="mt-4 flex flex-col gap-3 lg:flex-row">
                  <Input
                    placeholder="Enter command and press enter to send"
                    className="h-10 border-zinc-700 bg-zinc-900/80 font-mono text-sm text-slate-100 placeholder:text-slate-500"
                  />
                  <Button type="button" size="sm" className="h-10 px-4 lg:min-w-24">
                    <Send className="size-4" />
                    Send
                  </Button>
                </div>
              </>
            ) : (
              <div className="max-h-[38rem] min-h-[30rem] overflow-y-auto rounded-xl border border-zinc-800 bg-[#121212] flex flex-col items-center justify-center gap-6 px-4 py-8">
                <div className="rounded-full bg-muted/20 p-6">
                  <Plug className="size-12 text-muted-foreground" />
                </div>
                <div className="text-center space-y-2">
                  <h3 className="text-lg font-semibold text-slate-200">Socket Not Connected</h3>
                  <p className="text-sm text-slate-400 max-w-md">
                    The terminal is not connected to the backend socket. 
                    Please check the connection settings and ensure the target service is running.
                  </p>
                </div>
                <div className="grid gap-2 text-sm text-slate-400 bg-muted/10 rounded-lg p-4 w-full max-w-sm">
                  <div className="flex justify-between">
                    <span>Connection Type:</span>
                    <span className="font-mono">{item.socket_connection_type || "local"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Host:</span>
                    <span className="font-mono">{item.socket_host || "localhost"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Port:</span>
                    <span className="font-mono">{item.socket_port || 9000}</span>
                  </div>
                </div>
                <Button variant="outline" size="sm" className="mt-2">
                  <Plug className="size-4 mr-2" />
                  Retry Connection
                </Button>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <h2 className="text-xl font-semibold mb-4">Key Information</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <CopyValue label="ID" value={item.id} />
          <KeyValue label="Status" value={item.status} />
          <KeyValue label="Owner ID" value={item.owner_id} />
          <KeyValue label="Connection Type" value={item.socket_connection_type} />
          <KeyValue label="Socket Host" value={item.socket_host} />
          <KeyValue label="Socket Port" value={item.socket_port?.toString()} />
          <KeyValue label="Socket Connected" value={item.socket_connected ? "Yes" : "No"} />
          <KeyValue label="Socket Unique ID" value={item.socket_unique_id} />
          <KeyValue label="Command" value={item.command} />
          <KeyValue label="Executable Path" value={item.executable_path} />
          <KeyValue label="Working Directory" value={item.working_directory} />
          <KeyValue label="Log Path" value={item.log_path} />
          <KeyValue label="Log Max Size (MB)" value={item.log_max_size_mb?.toString()} />
          <KeyValue label="Created At" value={formatDate(item.created_at)} />
          <KeyValue label="Updated At" value={formatDate(item.updated_at)} />
        </div>
      </section>
    </div>
  )
}

export const Route = createFileRoute("/_layout/items/$itemId")({
  component: ItemDetailRoute,
  head: () => ({
    meta: [
      {
        title: "Item Detail - TermMan",
      },
    ],
  }),
})

function ItemDetailRoute() {
  const { itemId } = Route.useParams()
  const queryClient = useQueryClient()

  const cachedDetailItem = queryClient.getQueryData<ItemPublic>([
    "items",
    "detail",
    itemId,
  ])
  const cachedItems = queryClient.getQueryData<ItemsPublic>(["items"])
  const cachedListItem = getCachedItem(cachedItems, itemId)
  const storedItem = useMemo(() => getStoredItemSnapshot(itemId), [itemId])
  const seedItem = useMemo(
    () =>
      createFallbackItem(
        itemId,
        cachedDetailItem ?? cachedListItem ?? storedItem,
      ),
    [cachedDetailItem, cachedListItem, itemId, storedItem],
  )

  const { data, error, isError, isFetching, isPending } = useQuery({
    ...getItemQueryOptions(itemId),
    initialData: cachedDetailItem ?? cachedListItem ?? storedItem,
  })

  useEffect(() => {
    if (data) {
      saveItemSnapshot(data)
    }
  }, [data])

  const displayItem = data ?? seedItem
  const message = isError
    ? getErrorMessage(error)
    : !data && (isPending || isFetching)
      ? "Loading live detail data..."
      : undefined

  return (
    <ItemDetailPage
      item={displayItem}
      isLoading={isPending || isFetching}
      isUsingFallback={!data || isError}
      message={message}
    />
  )
}
