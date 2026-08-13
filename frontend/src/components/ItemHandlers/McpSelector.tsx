import { useEffect, useMemo, useState } from "react"
import { GripVertical, Loader2, Search, Server, X } from "lucide-react"

import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { LIST_PAGE_SIZE, LoadMoreButton } from "@/components/ItemHandlers/dispatcherShared"

export function MCPSelector({
  allServers,
  enabledServers,
  onServerToggle,
}: {
  allServers: any[]
  enabledServers: string[]
  onServerToggle: (serverName: string, enable: boolean) => Promise<void>
}) {
  const [searchQuery, setSearchQuery] = useState("")
  const [draggedServer, setDraggedServer] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<"enabled" | "available" | null>(
    null,
  )
  const [pendingServer, setPendingServer] = useState<string | null>(null)
  const [enabledVisibleCount, setEnabledVisibleCount] = useState(LIST_PAGE_SIZE)
  const [availableVisibleCount, setAvailableVisibleCount] =
    useState(LIST_PAGE_SIZE)

  const enabledServersList = useMemo(() => {
    return allServers.filter((s) => enabledServers.includes(s.name))
  }, [allServers, enabledServers])

  const availableServersList = useMemo(() => {
    return allServers.filter((s) => !enabledServers.includes(s.name))
  }, [allServers, enabledServers])

  const filteredAvailableServers = useMemo(() => {
    if (!searchQuery) return availableServersList
    return availableServersList.filter(
      (s) =>
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.description?.toLowerCase().includes(searchQuery.toLowerCase()),
    )
  }, [availableServersList, searchQuery])
  const visibleEnabledServers = enabledServersList.slice(0, enabledVisibleCount)
  const visibleAvailableServers = filteredAvailableServers.slice(
    0,
    availableVisibleCount,
  )
  const enabledRemainingCount = Math.max(
    enabledServersList.length - visibleEnabledServers.length,
    0,
  )
  const availableRemainingCount = Math.max(
    filteredAvailableServers.length - visibleAvailableServers.length,
    0,
  )

  useEffect(() => {
    setEnabledVisibleCount(LIST_PAGE_SIZE)
  }, [enabledServersList.length])

  useEffect(() => {
    setAvailableVisibleCount(LIST_PAGE_SIZE)
  }, [availableServersList.length, searchQuery])

  const handleDragStart = (e: React.DragEvent, serverName: string) => {
    setDraggedServer(serverName)
    e.dataTransfer.effectAllowed = "move"
  }

  const handleDragOver = (
    e: React.DragEvent,
    target: "enabled" | "available",
  ) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    setDropTarget(target)
  }

  const handleDragLeave = () => {
    setDropTarget(null)
  }

  const handleDrop = async (
    e: React.DragEvent,
    target: "enabled" | "available",
  ) => {
    e.preventDefault()
    setDropTarget(null)

    if (!draggedServer) return

    const isCurrentlyEnabled = enabledServers.includes(draggedServer)

    if (target === "enabled" && !isCurrentlyEnabled) {
      setPendingServer(draggedServer)
      await onServerToggle(draggedServer, true)
      setPendingServer(null)
    } else if (target === "available" && isCurrentlyEnabled) {
      setPendingServer(draggedServer)
      await onServerToggle(draggedServer, false)
      setPendingServer(null)
    }

    setDraggedServer(null)
  }

  const handleDragEnd = () => {
    setDraggedServer(null)
    setDropTarget(null)
  }

  const removeServer = async (serverName: string) => {
    setPendingServer(serverName)
    await onServerToggle(serverName, false)
    setPendingServer(null)
  }

  const addServer = async (serverName: string) => {
    if (!enabledServers.includes(serverName)) {
      setPendingServer(serverName)
      await onServerToggle(serverName, true)
      setPendingServer(null)
    }
  }

  return (
    <div className="flex gap-4 h-80">
      <div
        className={`flex-1 flex flex-col border rounded-lg overflow-hidden transition-colors ${
          dropTarget === "enabled"
            ? "border-purple-500 bg-purple-50/50 dark:bg-purple-950/50"
            : "border-border"
        }`}
        onDragOver={(e) => handleDragOver(e, "enabled")}
        onDragLeave={handleDragLeave}
        onDrop={(e) => handleDrop(e, "enabled")}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
          <div className="flex items-center gap-2">
            <Server className="size-4 text-purple-500" />
            <span className="text-sm font-medium">
              已启用 ({enabledServersList.length})
            </span>
          </div>
        </div>
        <ScrollArea className="flex-1">
          {enabledServersList.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <GripVertical className="size-8 mb-2 opacity-30" />
              <p className="text-sm text-center">拖拽 MCP Server 到此处启用</p>
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {visibleEnabledServers.map((server) => (
                <div
                  key={server.name}
                  draggable
                  onDragStart={(e) => handleDragStart(e, server.name)}
                  onDragEnd={handleDragEnd}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md bg-purple-100 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-800 cursor-grab active:cursor-grabbing transition-all ${
                    draggedServer === server.name ? "opacity-50 scale-95" : ""
                  } ${pendingServer === server.name ? "opacity-60" : ""}`}
                >
                  <GripVertical className="size-4 text-purple-600 dark:text-purple-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-purple-700 dark:text-purple-300 truncate">
                      {server.name}
                    </div>
                    {server.description && (
                      <div className="text-xs text-purple-600/70 dark:text-purple-400/70 truncate">
                        {server.description}
                      </div>
                    )}
                  </div>
                  {pendingServer === server.name ? (
                    <Loader2 className="size-4 text-purple-600 dark:text-purple-400 animate-spin" />
                  ) : (
                    <button
                      onClick={() => removeServer(server.name)}
                      className="p-1 hover:bg-purple-200 dark:hover:bg-purple-800 rounded transition-colors"
                    >
                      <X className="size-3 text-purple-600 dark:text-purple-400" />
                    </button>
                  )}
                </div>
              ))}
              <LoadMoreButton
                remainingCount={enabledRemainingCount}
                className="w-full"
                onClick={() =>
                  setEnabledVisibleCount((current) => current + LIST_PAGE_SIZE)
                }
              />
            </div>
          )}
        </ScrollArea>
      </div>

      <div
        className={`flex-1 flex flex-col border rounded-lg overflow-hidden transition-colors ${
          dropTarget === "available"
            ? "border-blue-500 bg-blue-50/50 dark:bg-blue-950/50"
            : "border-border"
        }`}
        onDragOver={(e) => handleDragOver(e, "available")}
        onDragLeave={handleDragLeave}
        onDrop={(e) => handleDrop(e, "available")}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
          <div className="flex items-center gap-2">
            <Server className="size-4 text-blue-500" />
            <span className="text-sm font-medium">
              可用服务器 ({availableServersList.length})
            </span>
          </div>
        </div>
        <div className="px-3 py-2 border-b">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input
              placeholder="搜索 MCP Server..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-8"
            />
          </div>
        </div>
        <ScrollArea className="flex-1">
          {filteredAvailableServers.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <Search className="size-8 mb-2 opacity-30" />
              <p className="text-sm text-center">
                {searchQuery ? "未找到匹配的服务器" : "所有服务器已启用"}
              </p>
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {visibleAvailableServers.map((server) => (
                <div
                  key={server.name}
                  draggable
                  onDragStart={(e) => handleDragStart(e, server.name)}
                  onDragEnd={handleDragEnd}
                  onClick={() => addServer(server.name)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md bg-muted/50 border border-border cursor-grab active:cursor-grabbing hover:bg-muted transition-all ${
                    draggedServer === server.name ? "opacity-50 scale-95" : ""
                  } ${pendingServer === server.name ? "opacity-60" : ""}`}
                >
                  {pendingServer === server.name ? (
                    <Loader2 className="size-4 text-muted-foreground shrink-0 animate-spin" />
                  ) : (
                    <GripVertical className="size-4 text-muted-foreground shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {server.name}
                    </div>
                    {server.description && (
                      <div className="text-xs text-muted-foreground truncate">
                        {server.description}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <LoadMoreButton
                remainingCount={availableRemainingCount}
                className="w-full"
                onClick={() =>
                  setAvailableVisibleCount(
                    (current) => current + LIST_PAGE_SIZE,
                  )
                }
              />
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}
