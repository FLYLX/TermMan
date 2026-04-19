import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Plug,
  RefreshCw,
  Shield,
  Trash2,
  User,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { ItemHandlerAssociationsService, ItemsService } from "@/client/sdk.gen"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - TermMan",
      },
    ],
  }),
})

type Subscriber = {
  sid: string
  user_uuid: string
  user_name: string
  ip: string
  type: string
  join_time: number
  last_active_time: number
}

type Item = {
  id: string
  title: string
  description: string | null
  status: string
  owner_id: string
  daemon_id?: string
  daemon_url?: string
  daemon_online?: boolean
  daemon_status?: string
  subscribers?: Subscriber[]
  browser_count?: number
  backend_connected?: boolean
  [key: string]: unknown
}

type Daemon = {
  id: string
  url: string
  online: boolean
  status: string
  items: Item[]
}

function Dashboard() {
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedDaemons, setExpandedDaemons] = useState<
    Record<string, boolean>
  >({})
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>(
    {},
  )
  const [disconnectDialog, setDisconnectDialog] = useState<{
    open: boolean
    itemId: string
    itemTitle: string
    userUuid: string
    userName: string
    ip: string
  } | null>(null)
  const [disconnecting, setDisconnecting] = useState(false)

  const isAdmin = currentUser?.is_superuser ?? false

  const fetchItems = useCallback(async () => {
    try {
      setLoading(true)
      const response = await ItemsService.readItems()
      setItems((response as { data: Item[] }).data || [])
    } catch (error) {
      console.error("Failed to fetch items:", error)
      toast.error("Failed to fetch items. Please try again.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleDisconnectUser = async () => {
    if (!disconnectDialog) return

    try {
      setDisconnecting(true)
      await ItemsService.disconnectItemSubscriber({
        id: disconnectDialog.itemId,
        requestBody: {
          user_uuid: disconnectDialog.userUuid,
          ip_address: disconnectDialog.ip,
        },
      })
      toast.success("User disconnected successfully.")
      await fetchItems()
    } catch (error) {
      console.error("Failed to disconnect user:", error)
      toast.error("Failed to disconnect user. Please try again.")
    } finally {
      setDisconnecting(false)
      setDisconnectDialog(null)
    }
  }

  const handleReconnectDaemon = async (daemonId: string) => {
    try {
      const result = (await ItemsService.reconnectDaemon({ daemonId })) as {
        success: boolean
        message: string
      }
      if (result.success) {
        toast.success(result.message)
        await fetchItems()
      } else {
        toast.error(result.message)
      }
    } catch (error) {
      console.error("Failed to reconnect daemon:", error)
      toast.error("Failed to reconnect daemon. Please try again.")
    }
  }

  const toggleDaemonExpand = (daemonId: string) => {
    setExpandedDaemons((prev) => ({
      ...prev,
      [daemonId]: !prev[daemonId],
    }))
  }

  const toggleItemExpand = (itemId: string) => {
    setExpandedItems((prev) => ({
      ...prev,
      [itemId]: !prev[itemId],
    }))
  }

  const groupItemsByDaemon = (items: Item[]): Daemon[] => {
    const daemonMap: Record<string, Daemon> = {}

    items.forEach((item) => {
      const daemonUrl = item.daemon_url || "unknown-daemon"
      const daemonId = item.daemon_id || daemonUrl

      if (!daemonMap[daemonId]) {
        daemonMap[daemonId] = {
          id: daemonId,
          url: daemonUrl,
          online: item.daemon_online ?? false,
          status: item.daemon_status ?? "unknown",
          items: [],
        }
      }

      daemonMap[daemonId].items.push(item)
    })

    return Object.values(daemonMap)
  }

  const daemons = groupItemsByDaemon(items)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl truncate max-w-sm">
            Hi, {currentUser?.full_name || currentUser?.email} 👋
          </h1>
          <p className="text-muted-foreground">
            Welcome back, nice to see you again!
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin ? (
            <div className="flex items-center gap-1 text-sm text-primary">
              <Shield className="h-4 w-4" />
              <span>Admin</span>
            </div>
          ) : (
            <div className="flex items-center gap-1 text-sm text-muted-foreground">
              <User className="h-4 w-4" />
              <span>User</span>
            </div>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{isAdmin ? "All Items Dashboard" : "My Items"}</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={fetchItems}
            disabled={loading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p>Loading items...</p>
          ) : items.length === 0 ? (
            <Alert>
              <AlertTitle>No items found</AlertTitle>
              <AlertDescription>
                {isAdmin
                  ? "There are no items in the system."
                  : "You don't have any items yet."}
              </AlertDescription>
            </Alert>
          ) : isAdmin ? (
            <div className="space-y-4">
              {daemons.map((daemon) => (
                <div key={daemon.id} className="border rounded-lg">
                  <div
                    className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted"
                    onClick={() => toggleDaemonExpand(daemon.id)}
                  >
                    <div className="flex items-center">
                      {expandedDaemons[daemon.id] ? (
                        <ChevronDown className="h-5 w-5 mr-2" />
                      ) : (
                        <ChevronRight className="h-5 w-5 mr-2" />
                      )}
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium">Daemon: {daemon.id}</h3>
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs ${
                              daemon.online
                                ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                                : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                            }`}
                          >
                            {daemon.online ? "Online" : "Offline"}
                          </span>
                          {!daemon.online && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 px-2"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleReconnectDaemon(daemon.id)
                              }}
                            >
                              <RefreshCw className="h-3 w-3 mr-1" />
                              Reconnect
                            </Button>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground">
                          URL: {daemon.url}
                        </p>
                      </div>
                    </div>
                    <div className="text-sm font-medium">
                      {daemon.items.length} items
                    </div>
                  </div>

                  {expandedDaemons[daemon.id] && (
                    <div className="border-t">
                      {daemon.items.map((item) => (
                        <ItemCard
                          key={item.id}
                          item={item}
                          expanded={expandedItems[item.id]}
                          onToggleExpand={() => toggleItemExpand(item.id)}
                          onDisconnectUser={(userUuid, userName, ip) =>
                            setDisconnectDialog({
                              open: true,
                              itemId: item.id,
                              itemTitle: item.title,
                              userUuid,
                              userName,
                              ip,
                            })
                          }
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-4">
              {items.map((item) => (
                <ItemCard
                  key={item.id}
                  item={item}
                  expanded={expandedItems[item.id]}
                  onToggleExpand={() => toggleItemExpand(item.id)}
                  onDisconnectUser={(userUuid, userName, ip) =>
                    setDisconnectDialog({
                      open: true,
                      itemId: item.id,
                      itemTitle: item.title,
                      userUuid,
                      userName,
                      ip,
                    })
                  }
                  showOwner={false}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={disconnectDialog?.open}
        onOpenChange={(open) => !open && setDisconnectDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disconnect User</DialogTitle>
            <DialogDescription>
              Are you sure you want to disconnect user{" "}
              <strong>
                {disconnectDialog?.userName || disconnectDialog?.userUuid}
              </strong>{" "}
              (IP: {disconnectDialog?.ip}) from item{" "}
              <strong>{disconnectDialog?.itemTitle}</strong>?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDisconnectDialog(null)}
              disabled={disconnecting}
            >
              Cancel
            </Button>
            <Button
              onClick={handleDisconnectUser}
              disabled={disconnecting}
              variant="destructive"
            >
              {disconnecting ? "Disconnecting..." : "Disconnect"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ItemCard({
  item,
  expanded,
  onToggleExpand,
  onDisconnectUser,
  showOwner = true,
}: {
  item: Item
  expanded: boolean
  onToggleExpand: () => void
  onDisconnectUser: (userUuid: string, userName: string, ip: string) => void
  showOwner?: boolean
}) {
  const subscribers = item.subscribers ?? []
  const [handlers, setHandlers] = useState<any[]>([])
  const [loadingHandlers, setLoadingHandlers] = useState(false)

  useEffect(() => {
    const fetchHandlers = async () => {
      if (expanded && item.id) {
        setLoadingHandlers(true)
        try {
          const result =
            await ItemHandlerAssociationsService.getHandlersForItem({
              itemId: item.id,
            })
          setHandlers(result || [])
        } catch (error) {
          console.error("Failed to fetch handlers:", error)
        } finally {
          setLoadingHandlers(false)
        }
      }
    }
    fetchHandlers()
  }, [expanded, item.id])

  return (
    <div className="border-b last:border-b-0 ml-4">
      <div
        className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted"
        onClick={onToggleExpand}
      >
        <div className="flex items-center">
          {expanded ? (
            <ChevronDown className="h-5 w-5 mr-2" />
          ) : (
            <ChevronRight className="h-5 w-5 mr-2" />
          )}
          <div>
            <div className="flex items-center gap-2">
              <Link
                to="/items/$itemId"
                params={{ itemId: item.id }}
                className="font-medium hover:text-blue-600 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {item.title}
              </Link>
              {handlers.length > 0 && (
                <Link
                  to="/item-handlers/$itemHandlerId"
                  params={{ itemHandlerId: handlers[0].id }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Badge
                    variant="outline"
                    className="text-xs gap-1 cursor-pointer hover:bg-primary/10"
                  >
                    <Plug className="size-3" />
                    {handlers[0].name}
                  </Badge>
                </Link>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              {item.description || "No description"}
            </p>
            {showOwner && (
              <p className="text-xs text-muted-foreground">
                Owner: {item.owner_id}
              </p>
            )}
          </div>
        </div>
        <div className="text-sm flex items-center gap-2">
          <span
            className={`px-2 py-1 rounded-full text-xs ${
              item.status === "running"
                ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200"
            }`}
          >
            {item.status}
          </span>
          <span className="text-muted-foreground">
            {item.browser_count ?? 0} connected
          </span>
        </div>
      </div>

      {expanded && (
        <div className="p-4 bg-muted/50 space-y-4">
          {handlers.length > 0 && (
            <div>
              <h5 className="font-medium text-sm mb-2 flex items-center gap-1">
                <Plug className="size-4" />
                Managed by:
              </h5>
              <div className="flex flex-wrap gap-2">
                {handlers.map((handler) => (
                  <Link
                    key={handler.id}
                    to="/item-handlers/$itemHandlerId"
                    params={{ itemHandlerId: handler.id }}
                  >
                    <Badge
                      variant="secondary"
                      className="cursor-pointer hover:bg-primary/20"
                    >
                      {handler.name}
                    </Badge>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {loadingHandlers ? (
            <p className="text-sm text-muted-foreground">Loading handlers...</p>
          ) : null}

          {subscribers.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No users connected to this item
            </p>
          ) : (
            <div className="space-y-2">
              <h5 className="font-medium text-sm">Connected Users:</h5>
              {subscribers.map((sub) => (
                <div
                  key={sub.sid}
                  className="flex items-center justify-between p-3 border rounded-lg bg-background"
                >
                  <div>
                    <p className="font-medium text-sm">
                      {sub.user_name || sub.user_uuid}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      IP: {sub.ip}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Joined: {new Date(sub.join_time * 1000).toLocaleString()}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive hover:bg-destructive/10"
                    onClick={() =>
                      onDisconnectUser(sub.user_uuid, sub.user_name, sub.ip)
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                    <span className="sr-only">Disconnect user</span>
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Dashboard
