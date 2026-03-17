import { createFileRoute, Link } from "@tanstack/react-router"
import { useState, useEffect } from "react"
import { ItemsService } from "@/client/sdk.gen"
import useAuth from "@/hooks/useAuth"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - FastAPI Template",
      },
    ],
  }),
})

function Dashboard() {
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  
  // 展开/折叠状态管理
  const [expandedDaemons, setExpandedDaemons] = useState<Record<string, boolean>>({
    // 默认展开所有daemon
  })
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({
    // 默认展开所有item
  })

  // 定义类型 - 根据新的连接表结构
  type ConnectedUser = {
    user_uuid: string
    ip: string
  }

  type Item = {
    id: string
    title: string
    description: string
    status: string
    connected_users: Record<string, ConnectedUser>
    daemon_id?: string
    daemon_url?: string
    [key: string]: any
  }

  type Daemon = {
    id: string
    url: string
    items: Item[]
  }

  // 获取项目列表
  useEffect(() => {
    const fetchItems = async () => {
      try {
        setLoading(true)
        const response = await ItemsService.readItems()
        setItems(response.data || [])
      } catch (error) {
        console.error("Failed to fetch items:", error)
        toast.error("Failed to fetch items. Please try again.")
      } finally {
        setLoading(false)
      }
    }

    fetchItems()
  }, [])

  // 获取已连接的用户列表 - 根据新连接表结构 {sid: {user_uuid, ip}}
  const getConnectedUsers = (item: Item) => {
    return Object.entries(item.connected_users || {}).map(([sid, connInfo]) => ({
      sid,
      userUuid: connInfo.user_uuid || "unknown",
      ip: connInfo.ip || "unknown"
    }))
  }

  // 断开用户连接
  const handleDisconnectUser = async (itemId: string, userUuid: string) => {
    try {
      await ItemsService.disconnectUserFromItem({
        id: itemId,
        user_uuid: userUuid
      })
      toast.success("User disconnected successfully.")

      // 刷新项目列表
      const response = await ItemsService.readItems()
      setItems(response.data || [])
    } catch (error) {
      console.error("Failed to disconnect user:", error)
      toast.error("Failed to disconnect user. Please try again.")
    }
  }

  // 切换daemon展开/折叠状态
  const toggleDaemonExpand = (daemonId: string) => {
    setExpandedDaemons(prev => ({
      ...prev,
      [daemonId]: !prev[daemonId]
    }))
  }

  // 切换item展开/折叠状态
  const toggleItemExpand = (itemId: string) => {
    setExpandedItems(prev => ({
      ...prev,
      [itemId]: !prev[itemId]
    }))
  }

  // 按daemon分组items
  const groupItemsByDaemon = (items: Item[]): Daemon[] => {
    const daemonMap: Record<string, Daemon> = {}

    items.forEach(item => {
      // 使用daemon_url或daemon_id作为daemon的唯一标识
      const daemonUrl = item.daemon_url || "unknown-daemon"
      const daemonId = item.daemon_id || daemonUrl

      if (!daemonMap[daemonId]) {
        daemonMap[daemonId] = {
          id: daemonId,
          url: daemonUrl,
          items: []
        }
      }

      daemonMap[daemonId].items.push(item)
    })

    return Object.values(daemonMap)
  }

  // 按daemon分组items
  const daemons = groupItemsByDaemon(items)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl truncate max-w-sm">
          Hi, {currentUser?.full_name || currentUser?.email} 👋
        </h1>
        <p className="text-muted-foreground">
          Welcome back, nice to see you again!!!
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connected Items Dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p>Loading items...</p>
          ) : items.length === 0 ? (
            <Alert variant="info">
              <AlertTitle>No items found</AlertTitle>
              <AlertDescription>You don't have any items yet.</AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-4">
              {/* 显示所有daemon节点 */}
              {daemons.map((daemon) => (
                <div key={daemon.id} className="border rounded-lg">
                  {/* Daemon头部 - 可点击展开/折叠 */}
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
                        <h3 className="font-medium">Daemon: {daemon.id}</h3>
                        <p className="text-sm text-muted-foreground">URL: {daemon.url}</p>
                      </div>
                    </div>
                    <div className="text-sm font-medium">
                      {daemon.items.length} items
                    </div>
                  </div>

                  {/* Daemon展开内容 - 显示所有items */}
                  {expandedDaemons[daemon.id] && (
                    <div className="border-t">
                      {daemon.items.map((item) => {
                        const connectedUsers = getConnectedUsers(item)
                        return (
                          <div key={item.id} className="border-b last:border-b-0 ml-4">
                            {/* Item头部 - 可点击展开/折叠 */}
                            <div 
                              className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted" 
                              onClick={() => toggleItemExpand(item.id)}
                            >
                              <div className="flex items-center">
                                {expandedItems[item.id] ? (
                                  <ChevronDown className="h-5 w-5 mr-2" />
                                ) : (
                                  <ChevronRight className="h-5 w-5 mr-2" />
                                )}
                                <div>
                                  <Link to={`/items/${item.id}`} className="font-medium hover:text-blue-600 hover:underline" onClick={(e) => e.stopPropagation()}>
                                    {item.title}
                                  </Link>
                                  <p className="text-sm text-muted-foreground">{item.description || "No description"}</p>
                                </div>
                              </div>
                              <div className="text-sm">
                                <span className={`px-2 py-1 rounded-full text-xs ${item.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                  {item.status}
                                </span>
                                <span className="ml-2">
                                  {connectedUsers.length} connected users
                                </span>
                              </div>
                            </div>

                            {/* Item展开内容 - 显示已连接的用户 */}
                            {expandedItems[item.id] && (
                              <div className="p-4 bg-muted/50">
                                {connectedUsers.length === 0 ? (
                                  <p className="text-sm text-muted-foreground">No users connected to this item</p>
                                ) : (
                                  <div className="space-y-2">
                                    <h5 className="font-medium text-sm">Connected Users:</h5>
                                    {connectedUsers.map((user) => (
                                      <div key={user.sid} className="flex items-center justify-between p-3 border rounded-lg bg-white">
                                        <div>
                                          <p className="font-medium text-sm">{user.userUuid}</p>
                                          <p className="text-xs text-muted-foreground">SID: {user.sid} | IP: {user.ip}</p>
                                        </div>
                                        <div className="flex items-center">
                                          <Button 
                                            variant="ghost" 
                                            size="icon" 
                                            className="h-7 w-7 text-destructive hover:bg-destructive/10"
                                            onClick={() => handleDisconnectUser(item.id, user.userUuid)}
                                          >
                                            <Trash2 className="h-4 w-4" />
                                            <span className="sr-only">Disconnect user</span>
                                          </Button>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}