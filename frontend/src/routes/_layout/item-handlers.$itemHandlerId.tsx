import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronRight,
  GripVertical,
  Loader2,
  Search,
  Server,
  Settings,
  Terminal,
  X,
  Zap,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ApiError,
  ItemHandlerAssociationsService,
  ItemHandlersService,
  ItemsService,
  McpService,
  SkillsService,
} from "@/client"
import { KnowledgeBindingSelector } from "@/components/Knowledge/KnowledgeBindingSelector"
import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/item-handlers/$itemHandlerId")({
  component: ItemHandlerDetail,
  head: () => ({
    meta: [
      {
        title: "ItemHandler Detail - TermMan",
      },
    ],
  }),
})

function getItemHandlerQueryOptions(itemHandlerId: string) {
  return {
    queryFn: () => ItemHandlersService.readItemHandler({ id: itemHandlerId }),
    queryKey: ["itemHandler", itemHandlerId],
  }
}

function formatDate(dateString: string | undefined | null, localeTag: string) {
  if (!dateString) return null
  return new Date(dateString).toLocaleString(localeTag)
}

function normalizeOptionalText(value: string) {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  const { t } = useI18n()

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">
        {value || t("common.notAvailable")}
      </span>
    </div>
  )
}

type ItemWithStatus = {
  id: string
  title: string
  description?: string | null
  status?: string
}

type NodePosition = {
  x: number
  y: number
}

function ItemWithHandlers({
  item,
  currentHandlerId,
  isConnected,
}: {
  item: any
  currentHandlerId: string
  isConnected: boolean
}) {
  const { t } = useI18n()
  const [isExpanded, setIsExpanded] = useState(false)
  const [handlers, setHandlers] = useState<any[]>([])

  const { refetch } = useQuery({
    queryFn: () =>
      ItemHandlerAssociationsService.getHandlersForItem({ itemId: item.id }),
    queryKey: ["item-handlers", item.id],
    enabled: false,
  })

  const toggleExpand = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!isExpanded) {
      const result = await refetch()
      setHandlers((result.data as any[]) || [])
    }
    setIsExpanded(!isExpanded)
  }

  return (
    <div className="rounded-lg border overflow-hidden">
      <div
        className={`flex items-center gap-2 p-2 transition-colors ${isConnected ? "bg-green-50 dark:bg-green-950" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}
      >
        <button
          onClick={toggleExpand}
          className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded"
        >
          <ChevronRight
            className={`size-4 text-slate-400 transition-transform ${isExpanded ? "rotate-90" : ""}`}
          />
        </button>
        <Link
          to="/items/$itemId"
          params={{ itemId: item.id }}
          className="flex items-center gap-2 flex-1 min-w-0"
        >
          <Terminal className="size-4 text-slate-500 shrink-0" />
          <span className="text-sm font-medium truncate">
            {item.title || item.id}
          </span>
        </Link>
        {isConnected && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
            {t("common.connected")}
          </span>
        )}
        <span
          className={`text-xs px-2 py-0.5 rounded-full ${item.status === "running" ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"}`}
        >
          {item.status === "running" ? t("common.online") : t("common.offline")}
        </span>
      </div>
      {isExpanded && (
        <div className="border-t bg-slate-50 dark:bg-slate-900 p-2">
          {handlers.length === 0 ? (
            <p className="text-xs text-muted-foreground px-2">
              {t("itemHandlers.detail.noHandlersConnected")}
            </p>
          ) : (
            <div className="space-y-1">
              {handlers.map((handler: any) => (
                <Link
                  key={handler.id}
                  to="/item-handlers/$itemHandlerId"
                  params={{ itemHandlerId: handler.id }}
                  className={`flex items-center gap-2 px-2 py-1 rounded text-sm hover:bg-slate-200 dark:hover:bg-slate-800 ${handler.id === currentHandlerId ? "bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300" : "text-slate-600 dark:text-slate-400"}`}
                >
                  <Zap className="size-3" />
                  <span>{handler.name}</span>
                  {handler.id === currentHandlerId && (
                    <span className="text-xs ml-auto">
                      ({t("common.current")})
                    </span>
                  )}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SkillSelector({
  allSkills,
  enabledSkills,
  onSkillToggle,
}: {
  allSkills: any[]
  enabledSkills: string[]
  onSkillToggle: (skillId: string, enable: boolean) => Promise<void>
}) {
  const [searchQuery, setSearchQuery] = useState("")
  const [draggedSkill, setDraggedSkill] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<"enabled" | "available" | null>(
    null,
  )
  const [pendingSkill, setPendingSkill] = useState<string | null>(null)

  const enabledSkillsList = useMemo(() => {
    return allSkills.filter((s) => enabledSkills.includes(s.skill_id))
  }, [allSkills, enabledSkills])

  const availableSkillsList = useMemo(() => {
    return allSkills.filter((s) => !enabledSkills.includes(s.skill_id))
  }, [allSkills, enabledSkills])

  const filteredAvailableSkills = useMemo(() => {
    if (!searchQuery) return availableSkillsList
    return availableSkillsList.filter(
      (s) =>
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.description?.toLowerCase().includes(searchQuery.toLowerCase()),
    )
  }, [availableSkillsList, searchQuery])

  const handleDragStart = (e: React.DragEvent, skillId: string) => {
    setDraggedSkill(skillId)
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

    if (!draggedSkill) return

    const isCurrentlyEnabled = enabledSkills.includes(draggedSkill)

    if (target === "enabled" && !isCurrentlyEnabled) {
      setPendingSkill(draggedSkill)
      await onSkillToggle(draggedSkill, true)
      setPendingSkill(null)
    } else if (target === "available" && isCurrentlyEnabled) {
      setPendingSkill(draggedSkill)
      await onSkillToggle(draggedSkill, false)
      setPendingSkill(null)
    }

    setDraggedSkill(null)
  }

  const handleDragEnd = () => {
    setDraggedSkill(null)
    setDropTarget(null)
  }

  const removeSkill = async (skillId: string) => {
    setPendingSkill(skillId)
    await onSkillToggle(skillId, false)
    setPendingSkill(null)
  }

  const addSkill = async (skillId: string) => {
    if (!enabledSkills.includes(skillId)) {
      setPendingSkill(skillId)
      await onSkillToggle(skillId, true)
      setPendingSkill(null)
    }
  }

  return (
    <div className="flex gap-4 h-80">
      <div
        className={`flex-1 flex flex-col border rounded-lg overflow-hidden transition-colors ${
          dropTarget === "enabled"
            ? "border-green-500 bg-green-50/50 dark:bg-green-950/50"
            : "border-border"
        }`}
        onDragOver={(e) => handleDragOver(e, "enabled")}
        onDragLeave={handleDragLeave}
        onDrop={(e) => handleDrop(e, "enabled")}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
          <div className="flex items-center gap-2">
            <Zap className="size-4 text-green-500" />
            <span className="text-sm font-medium">
              已启用 ({enabledSkillsList.length})
            </span>
          </div>
        </div>
        <ScrollArea className="flex-1">
          {enabledSkillsList.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <GripVertical className="size-8 mb-2 opacity-30" />
              <p className="text-sm text-center">拖拽技能到此处启用</p>
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {enabledSkillsList.map((skill) => (
                <div
                  key={skill.skill_id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, skill.skill_id)}
                  onDragEnd={handleDragEnd}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md bg-green-100 dark:bg-green-900/30 border border-green-200 dark:border-green-800 cursor-grab active:cursor-grabbing transition-all ${
                    draggedSkill === skill.skill_id ? "opacity-50 scale-95" : ""
                  } ${pendingSkill === skill.skill_id ? "opacity-60" : ""}`}
                >
                  <GripVertical className="size-4 text-green-600 dark:text-green-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-green-700 dark:text-green-300 truncate">
                      {skill.name}
                    </div>
                    {skill.description && (
                      <div className="text-xs text-green-600/70 dark:text-green-400/70 truncate">
                        {skill.description}
                      </div>
                    )}
                  </div>
                  {pendingSkill === skill.skill_id ? (
                    <Loader2 className="size-4 text-green-600 dark:text-green-400 animate-spin" />
                  ) : (
                    <button
                      onClick={() => removeSkill(skill.skill_id)}
                      className="p-1 hover:bg-green-200 dark:hover:bg-green-800 rounded transition-colors"
                    >
                      <X className="size-3 text-green-600 dark:text-green-400" />
                    </button>
                  )}
                </div>
              ))}
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
            <Terminal className="size-4 text-blue-500" />
            <span className="text-sm font-medium">
              可用技能 ({availableSkillsList.length})
            </span>
          </div>
        </div>
        <div className="px-3 py-2 border-b">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input
              placeholder="搜索技能..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-8"
            />
          </div>
        </div>
        <ScrollArea className="flex-1">
          {filteredAvailableSkills.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <Search className="size-8 mb-2 opacity-30" />
              <p className="text-sm text-center">
                {searchQuery ? "未找到匹配的技能" : "所有技能已启用"}
              </p>
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {filteredAvailableSkills.map((skill) => (
                <div
                  key={skill.skill_id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, skill.skill_id)}
                  onDragEnd={handleDragEnd}
                  onClick={() => addSkill(skill.skill_id)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md bg-muted/50 border border-border cursor-grab active:cursor-grabbing hover:bg-muted transition-all ${
                    draggedSkill === skill.skill_id ? "opacity-50 scale-95" : ""
                  } ${pendingSkill === skill.skill_id ? "opacity-60" : ""}`}
                >
                  {pendingSkill === skill.skill_id ? (
                    <Loader2 className="size-4 text-muted-foreground shrink-0 animate-spin" />
                  ) : (
                    <GripVertical className="size-4 text-muted-foreground shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {skill.name}
                    </div>
                    {skill.description && (
                      <div className="text-xs text-muted-foreground truncate">
                        {skill.description}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}

function MCPSelector({
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
              {enabledServersList.map((server) => (
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
              {filteredAvailableServers.map((server) => (
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
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}

function ConnectionDiagram({
  itemHandler,
  connectedItems,
  availableItems,
  onConnect,
  onDisconnect,
}: {
  itemHandler: { id: string; name: string }
  connectedItems: ItemWithStatus[]
  availableItems: ItemWithStatus[]
  onConnect: (itemId: string) => void
  onDisconnect: (itemId: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [hoveredItem, setHoveredItem] = useState<string | null>(null)
  const [pendingLine, setPendingLine] = useState<{
    startX: number
    startY: number
    endX: number
    endY: number
    sourceId: string | null
  } | null>(null)
  const [isDrawingLine, setIsDrawingLine] = useState(false)
  const [draggingNode, setDraggingNode] = useState<string | null>(null)
  const [nodePositions, setNodePositions] = useState<
    Record<string, NodePosition>
  >({})
  const [dragStartPos, setDragStartPos] = useState<{
    x: number
    y: number
  } | null>(null)
  const [hasDragged, setHasDragged] = useState(false)

  const connected = useMemo(() => connectedItems || [], [connectedItems])
  const available = useMemo(() => availableItems || [], [availableItems])
  const allItems = useMemo(
    () => [...connected, ...available],
    [connected, available],
  )
  const connectedIds = useMemo(
    () => new Set(connected.map((item) => item.id)),
    [connected],
  )

  const itemNodeHeight = 40
  const handlerRadius = 45
  const padding = 50
  const calculatedHeight = Math.max(
    400,
    allItems.length * 70 + padding * 2 + itemNodeHeight,
  )

  const getHandlerDefaultY = useCallback(() => {
    const connectedCount = connected.length
    if (connectedCount === 0) {
      return calculatedHeight / 2
    }
    const availableHeight = calculatedHeight - padding * 2
    const spacing = Math.min(70, availableHeight / Math.max(connectedCount, 1))
    const totalHeight = (connectedCount - 1) * spacing
    const startY = padding - 20 + (availableHeight - totalHeight) / 2

    if (connectedCount % 2 === 1) {
      const middleIndex = Math.floor(connectedCount / 2)
      return startY + middleIndex * spacing
    }
    const middleTop = startY + (connectedCount / 2 - 1) * spacing
    const middleBottom = startY + (connectedCount / 2) * spacing
    return (middleTop + middleBottom) / 2
  }, [connected.length, calculatedHeight])

  const defaultHandlerPos = useMemo(
    () => ({
      x: 80,
      y: getHandlerDefaultY(),
    }),
    [getHandlerDefaultY],
  )

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        setDimensions({
          width: Math.max(600, rect.width),
          height: calculatedHeight,
        })
      }
    }
    updateDimensions()
    window.addEventListener("resize", updateDimensions)
    const timer = setTimeout(updateDimensions, 100)
    return () => {
      window.removeEventListener("resize", updateDimensions)
      clearTimeout(timer)
    }
  }, [calculatedHeight])

  useEffect(() => {
    const nodeHalfHeight = itemNodeHeight / 2

    setNodePositions((prev) => {
      const newPositions: Record<string, NodePosition> = {}
      const availableHeight = calculatedHeight - padding * 2
      const spacing = Math.min(
        70,
        availableHeight / Math.max(allItems.length, 1),
      )
      const totalHeight = (allItems.length - 1) * spacing
      const startY = padding - 20 + (availableHeight - totalHeight) / 2

      allItems.forEach((item, index) => {
        if (prev[item.id]) {
          newPositions[item.id] = prev[item.id]
        } else {
          const y = Math.max(
            padding + nodeHalfHeight,
            Math.min(
              calculatedHeight - padding - nodeHalfHeight,
              startY + index * spacing,
            ),
          )
          newPositions[item.id] = { x: 450, y }
        }
      })

      return newPositions
    })
  }, [calculatedHeight, allItems.forEach, allItems.length])

  const handlerPos = nodePositions.__handler__ || defaultHandlerPos

  const getItemPos = (itemId: string): NodePosition => {
    return (
      nodePositions[itemId] || {
        x: 450,
        y: Math.max(
          padding + itemNodeHeight / 2,
          Math.min(
            calculatedHeight - padding - itemNodeHeight / 2,
            calculatedHeight / 2,
          ),
        ),
      }
    )
  }

  const startDrawingLine = (
    e: React.MouseEvent,
    sourceId: string | null,
    startX: number,
    startY: number,
  ) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (rect) {
      setIsDrawingLine(true)
      setPendingLine({
        startX,
        startY,
        endX: e.clientX - rect.left,
        endY: e.clientY - rect.top,
        sourceId,
      })
    }
  }

  const handleHandlerClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (hasDragged) {
      return
    }

    if (isDrawingLine && pendingLine) {
      if (pendingLine.sourceId) {
        if (!connectedIds.has(pendingLine.sourceId)) {
          onConnect(pendingLine.sourceId)
        }
      }
      setIsDrawingLine(false)
      setPendingLine(null)
    } else {
      startDrawingLine(e, null, handlerPos.x, handlerPos.y)
    }
  }

  const handleItemClick = (e: React.MouseEvent, itemId: string) => {
    e.preventDefault()
    e.stopPropagation()

    if (hasDragged) {
      return
    }

    if (isDrawingLine && pendingLine) {
      if (pendingLine.sourceId !== itemId) {
        if (pendingLine.sourceId === null && !connectedIds.has(itemId)) {
          onConnect(itemId)
        }
      }
      setIsDrawingLine(false)
      setPendingLine(null)
    } else {
      const itemPos = getItemPos(itemId)
      startDrawingLine(e, itemId, itemPos.x, itemPos.y)
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return

    if (dragStartPos && !hasDragged) {
      const dx = e.clientX - dragStartPos.x
      const dy = e.clientY - dragStartPos.y
      if (Math.sqrt(dx * dx + dy * dy) > 5) {
        setHasDragged(true)
      }
    }

    if (isDrawingLine && pendingLine) {
      setPendingLine({
        ...pendingLine,
        endX: e.clientX - rect.left,
        endY: e.clientY - rect.top,
      })
    }

    if (draggingNode && containerRef.current) {
      const nodeBound =
        draggingNode === "__handler__" ? handlerRadius : itemNodeHeight / 2
      const newX = Math.max(
        nodeBound,
        Math.min(dimensions.width - nodeBound, e.clientX - rect.left),
      )
      const newY = Math.max(
        nodeBound,
        Math.min(calculatedHeight - nodeBound, e.clientY - rect.top),
      )
      setNodePositions((prev) => ({
        ...prev,
        [draggingNode]: { x: newX, y: newY },
      }))
    }
  }

  const handleBackgroundClick = () => {
    if (isDrawingLine) {
      setIsDrawingLine(false)
      setPendingLine(null)
    }
  }

  const handleNodeDragStart = (e: React.MouseEvent, nodeId: string) => {
    if (isDrawingLine) return
    e.preventDefault()
    e.stopPropagation()
    setDraggingNode(nodeId)
    setDragStartPos({ x: e.clientX, y: e.clientY })
    setHasDragged(false)
  }

  const handleMouseUp = () => {
    setDraggingNode(null)
    setDragStartPos(null)
    setTimeout(() => setHasDragged(false), 0)
  }

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-xl border bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 select-none"
      style={{ height: calculatedHeight, minHeight: 400 }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onClick={handleBackgroundClick}
    >
      <svg width="100%" height={calculatedHeight} className="absolute inset-0">
        <defs>
          <linearGradient
            id="lineGradient"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="0%"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.8">
              <animate
                attributeName="stop-color"
                values="#60a5fa;#a78bfa;#60a5fa"
                dur="2s"
                repeatCount="indefinite"
              />
            </stop>
            <stop offset="100%" stopColor="#a78bfa" stopOpacity="0.8">
              <animate
                attributeName="stop-color"
                values="#a78bfa;#60a5fa;#a78bfa"
                dur="2s"
                repeatCount="indefinite"
              />
            </stop>
          </linearGradient>
          <linearGradient
            id="pendingLineGradient"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="0%"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0.8" />
          </linearGradient>
          <radialGradient id="handlerGradient" cx="30%" cy="30%">
            <stop offset="0%" stopColor="#60a5fa" />
            <stop offset="100%" stopColor="#3b82f6" />
          </radialGradient>
          <radialGradient id="handlerActiveGradient" cx="30%" cy="30%">
            <stop offset="0%" stopColor="#93c5fd" />
            <stop offset="100%" stopColor="#60a5fa" />
          </radialGradient>
          <radialGradient id="itemConnectedGradient" cx="30%" cy="30%">
            <stop offset="0%" stopColor="#22c55e" />
            <stop offset="100%" stopColor="#16a34a" />
          </radialGradient>
          <radialGradient id="itemAvailableGradient" cx="30%" cy="30%">
            <stop offset="0%" stopColor="#64748b" />
            <stop offset="100%" stopColor="#475569" />
          </radialGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="1" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="glowStrong">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g className="connections">
          {connected.map((item, index) => {
            const itemPos = getItemPos(item.id)
            const isHovered = hoveredItem === item.id
            const startX = handlerPos.x + handlerRadius
            const endX = itemPos.x
            const startY = handlerPos.y
            const endY = itemPos.y
            const offset = (index - (connected.length - 1) / 2) * 15
            const midX = startX + 50 + Math.abs(offset)
            const pathD = `M ${startX} ${startY} C ${startX + 40} ${startY}, ${midX} ${startY}, ${midX} ${(startY + endY) / 2} S ${midX} ${endY}, ${endX} ${endY}`
            return (
              <g key={`line-${item.id}`}>
                <path
                  d={pathD}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={10}
                  className="cursor-pointer"
                  onDoubleClick={() => onDisconnect(item.id)}
                  onMouseEnter={() => setHoveredItem(item.id)}
                  onMouseLeave={() => setHoveredItem(null)}
                />
                <path
                  d={pathD}
                  fill="none"
                  stroke={isHovered ? "#ef4444" : "url(#lineGradient)"}
                  strokeWidth={isHovered ? 3 : 2}
                  pointerEvents="none"
                />
                {isHovered && (
                  <text
                    x={midX}
                    y={(startY + endY) / 2 - 10}
                    textAnchor="middle"
                    fill="#ef4444"
                    fontSize="10"
                    fontWeight="500"
                    pointerEvents="none"
                  >
                    Double-click to disconnect
                  </text>
                )}
                <circle r={3} fill="#a78bfa" filter="url(#glow)">
                  <animateMotion
                    dur="1.5s"
                    repeatCount="indefinite"
                    path={pathD}
                  />
                </circle>
              </g>
            )
          })}
        </g>

        {isDrawingLine && pendingLine && (
          <line
            x1={pendingLine.startX}
            y1={pendingLine.startY}
            x2={pendingLine.endX}
            y2={pendingLine.endY}
            stroke="url(#pendingLineGradient)"
            strokeWidth={2}
            strokeDasharray="8,4"
          />
        )}

        <g
          className={
            isDrawingLine
              ? "cursor-pointer"
              : "cursor-grab active:cursor-grabbing"
          }
        >
          <circle
            cx={handlerPos.x}
            cy={handlerPos.y}
            r={45}
            fill={
              isDrawingLine
                ? "url(#handlerActiveGradient)"
                : "url(#handlerGradient)"
            }
            stroke={isDrawingLine ? "#22c55e" : "#93c5fd"}
            strokeWidth={2}
            onClick={handleHandlerClick}
            onMouseDown={(e) =>
              !isDrawingLine && handleNodeDragStart(e, "__handler__")
            }
          />
          <text
            x={handlerPos.x}
            y={handlerPos.y - 8}
            textAnchor="middle"
            fill="white"
            fontSize="11"
            fontWeight="bold"
            pointerEvents="none"
          >
            {itemHandler.name.length > 10
              ? `${itemHandler.name.slice(0, 10)}...`
              : itemHandler.name}
          </text>
          <text
            x={handlerPos.x}
            y={handlerPos.y + 8}
            textAnchor="middle"
            fill="#bfdbfe"
            fontSize="9"
            pointerEvents="none"
          >
            Handler
          </text>
          <text
            x={handlerPos.x}
            y={handlerPos.y + 22}
            textAnchor="middle"
            fill={isDrawingLine ? "#86efac" : "#93c5fd"}
            fontSize="8"
            pointerEvents="none"
          >
            {isDrawingLine
              ? "Click item to connect"
              : `${connected.length} connected`}
          </text>
        </g>

        <g className="item-nodes">
          {allItems.map((item) => {
            const itemPos = getItemPos(item.id)
            const isConnected = connectedIds.has(item.id)
            const isHovered = hoveredItem === item.id

            return (
              <g
                key={item.id}
                className={
                  isDrawingLine && !isConnected
                    ? "cursor-pointer"
                    : "cursor-grab active:cursor-grabbing"
                }
                onMouseEnter={() => setHoveredItem(item.id)}
                onMouseLeave={() => setHoveredItem(null)}
              >
                <rect
                  x={itemPos.x - 70}
                  y={itemPos.y - 20}
                  width={140}
                  height={40}
                  rx={8}
                  fill={
                    isConnected
                      ? "url(#itemConnectedGradient)"
                      : "url(#itemAvailableGradient)"
                  }
                  stroke={
                    isConnected
                      ? "#22c55e"
                      : isDrawingLine
                        ? "#22c55e"
                        : "#64748b"
                  }
                  strokeWidth={isHovered ? 2 : 1}
                  onClick={(e) => handleItemClick(e, item.id)}
                  onMouseDown={(e) =>
                    !isDrawingLine && handleNodeDragStart(e, item.id)
                  }
                />
                <circle
                  cx={itemPos.x - 55}
                  cy={itemPos.y}
                  r={5}
                  fill={item.status === "running" ? "#22c55e" : "#64748b"}
                  pointerEvents="none"
                />
                <text
                  x={itemPos.x - 45}
                  y={itemPos.y - 4}
                  fill="white"
                  fontSize="10"
                  fontWeight="500"
                  pointerEvents="none"
                >
                  {item.title.length > 12
                    ? `${item.title.slice(0, 12)}...`
                    : item.title}
                </text>
                <text
                  x={itemPos.x - 45}
                  y={itemPos.y + 8}
                  fill={
                    isConnected
                      ? "#93c5fd"
                      : isDrawingLine
                        ? "#22c55e"
                        : "#94a3b8"
                  }
                  fontSize="8"
                  pointerEvents="none"
                >
                  {isConnected
                    ? "Connected"
                    : isDrawingLine
                      ? "Click to connect"
                      : "Click to draw line"}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      <div className="absolute top-4 left-4 flex items-center gap-2">
        <Badge
          variant="outline"
          className="bg-sky-500/20 border-sky-500/50 text-sky-300"
        >
          {connected.length} Connected
        </Badge>
        <Badge
          variant="outline"
          className="bg-green-500/20 border-green-500/50 text-green-300"
        >
          {available.length} Available
        </Badge>
      </div>

      <div className="absolute bottom-4 left-4 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-green-500" />{" "}
          Running
        </span>
        <span className="flex items-center gap-1 mt-1">
          <span className="inline-block w-2 h-2 rounded-full bg-slate-500" />{" "}
          Stopped
        </span>
      </div>
    </div>
  )
}

function ItemHandlerDetail() {
  const { itemHandlerId } = Route.useParams()
  const queryClient = useQueryClient()
  const { t, localeTag } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [isSaving, setIsSaving] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [activeTab, setActiveTab] = useState("connections")
  const [isConnectionsLoaded, setIsConnectionsLoaded] = useState(false)

  const { data: itemHandler, isLoading } = useQuery({
    ...getItemHandlerQueryOptions(itemHandlerId),
  })

  const { data: connectedItems, isLoading: connectedItemsLoading } = useQuery({
    queryFn: () =>
      ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: ["itemHandler-items", itemHandlerId],
    enabled: isConnectionsLoaded,
  })

  const { data: allItemsData, isLoading: allItemsLoading } = useQuery({
    queryFn: () => ItemsService.readItems(),
    queryKey: ["items"],
    enabled: isConnectionsLoaded,
  })

  const { data: skillsData, isLoading: skillsLoading } = useQuery({
    queryKey: ["skills"],
    queryFn: () => SkillsService.listSkills({}),
    enabled: activeTab === "skills",
  })

  const { data: mcpData, isLoading: mcpLoading } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: () => McpService.listMcpServers(),
    enabled: activeTab === "mcp",
  })

  const allItems = (allItemsData as any)?.data || []
  const connectedItemsList = (connectedItems as any[]) || []
  const connectedItemIds = new Set(
    connectedItemsList.map((item: any) => item.id),
  )
  const connectedItemCount = isConnectionsLoaded
    ? connectedItemsList.length
    : ((itemHandler as any)?.item_count ?? 0)
  const connectionsLoading =
    isConnectionsLoaded && (connectedItemsLoading || allItemsLoading)
  const availableItems = allItems.filter(
    (item: any) => !connectedItemIds.has(item.id),
  )

  const skills = skillsData?.data || []
  const enabledSkills = (itemHandler as any)?.enabled_skills ?? []
  const enabledKnowledgeFiles =
    (itemHandler as any)?.enabled_knowledge_files ?? []

  const mcpServers = mcpData?.data || []
  const enabledMcpServers = (itemHandler as any)?.enabled_mcp_servers ?? []

  const [editForm, setEditForm] = useState({
    name: "",
    model: "",
    api_key: "",
    api_url: "",
    enabled_skills: [] as string[],
  })

  useEffect(() => {
    if (itemHandler) {
      setEditForm({
        name: itemHandler.name,
        model: itemHandler.model ?? "",
        api_key: itemHandler.api_key ?? "",
        api_url: itemHandler.api_url ?? "",
        enabled_skills: (itemHandler as any).enabled_skills ?? [],
      })
    }
  }, [itemHandler])

  const startEditing = () => {
    if (itemHandler) {
      setEditForm({
        name: itemHandler.name,
        model: itemHandler.model ?? "",
        api_key: itemHandler.api_key ?? "",
        api_url: itemHandler.api_url ?? "",
        enabled_skills: enabledSkills,
      })
      setIsEditing(true)
      setActiveTab("config")
    }
  }

  const cancelEditing = () => {
    setIsEditing(false)
  }

  const saveChanges = async () => {
    const name = editForm.name.trim()
    if (!name) {
      showErrorToast(t("itemHandlers.nameRequired"))
      return
    }

    const requestBody = {
      name,
      model: normalizeOptionalText(editForm.model),
      api_key: normalizeOptionalText(editForm.api_key),
      api_url: normalizeOptionalText(editForm.api_url),
      enabled_skills: editForm.enabled_skills,
    }

    setIsSaving(true)
    try {
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody,
      })
      setEditForm((current) => ({
        ...current,
        name,
        model: requestBody.model ?? "",
        api_key: requestBody.api_key ?? "",
        api_url: requestBody.api_url ?? "",
      }))
      showSuccessToast(t("itemHandlers.detail.itemHandlerUpdated"))
      setIsEditing(false)
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
    } catch (error) {
      if (error instanceof ApiError) {
        showErrorToast(extractErrorMessage(error))
      } else {
        showErrorToast(t("itemHandlers.detail.itemHandlerUpdateFailed"))
      }
    } finally {
      setIsSaving(false)
    }
  }

  const handleSkillToggle = async (skillId: string, enable: boolean) => {
    try {
      const newSkills = enable
        ? [...enabledSkills, skillId]
        : enabledSkills.filter((id: string) => id !== skillId)
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody: { enabled_skills: newSkills },
      })
      showSuccessToast(
        enable
          ? t("itemHandlers.detail.skillEnabled")
          : t("itemHandlers.detail.skillDisabled"),
      )
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
    } catch (error) {
      if (error instanceof ApiError) {
        showErrorToast(extractErrorMessage(error))
      } else {
        showErrorToast(t("itemHandlers.detail.skillUpdateFailed"))
      }
    }
  }

  const handleMcpServerToggle = async (serverName: string, enable: boolean) => {
    try {
      const newServers = enable
        ? [...enabledMcpServers, serverName]
        : enabledMcpServers.filter((name: string) => name !== serverName)
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody: { enabled_mcp_servers: newServers },
      })
      showSuccessToast(
        enable
          ? t("itemHandlers.detail.mcpEnabled")
          : t("itemHandlers.detail.mcpDisabled"),
      )
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
    } catch (error) {
      if (error instanceof ApiError) {
        showErrorToast(extractErrorMessage(error))
      } else {
        showErrorToast(t("itemHandlers.detail.mcpUpdateFailed"))
      }
    }
  }

  const handleKnowledgeToggle = async (filePath: string, enable: boolean) => {
    try {
      const newFiles = enable
        ? [...enabledKnowledgeFiles, filePath]
        : enabledKnowledgeFiles.filter((path: string) => path !== filePath)
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody: { enabled_knowledge_files: newFiles } as any,
      })
      showSuccessToast(
        enable
          ? t("itemHandlers.detail.knowledgeEnabled")
          : t("itemHandlers.detail.knowledgeDisabled"),
      )
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
      queryClient.invalidateQueries({
        queryKey: ["itemHandler-knowledge", itemHandlerId],
      })
    } catch (error) {
      if (error instanceof ApiError) {
        showErrorToast(extractErrorMessage(error))
      } else {
        showErrorToast(t("itemHandlers.detail.knowledgeUpdateFailed"))
      }
    }
  }

  const handleConnect = async (itemId: string) => {
    try {
      await ItemHandlerAssociationsService.addItemToHandler({
        requestBody: {
          item_handler_id: itemHandlerId,
          item_id: itemId,
        },
      })
      showSuccessToast(t("itemHandlers.detail.itemConnected"))
      queryClient.invalidateQueries({
        queryKey: ["itemHandler-items", itemHandlerId],
      })
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    } catch (_error) {
      showErrorToast(t("itemHandlers.detail.itemConnectFailed"))
    }
  }

  const handleDisconnect = async (itemId: string) => {
    try {
      await ItemHandlerAssociationsService.removeItemFromHandler({
        itemHandlerId: itemHandlerId,
        itemId: itemId,
      })
      showSuccessToast(t("itemHandlers.detail.itemDisconnected"))
      queryClient.invalidateQueries({
        queryKey: ["itemHandler-items", itemHandlerId],
      })
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    } catch (_error) {
      showErrorToast(t("itemHandlers.detail.itemDisconnectFailed"))
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground">{t("common.loading")}</div>
      </div>
    )
  }

  if (!itemHandler) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground">
          {t("itemHandlers.detail.notFound")}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <section className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Link to="/item-handlers" className="hover:text-foreground">
            {t("itemHandlers.pageTitle")}
          </Link>
          <ChevronRight className="size-3.5" />
          <span className="text-foreground">{itemHandler.name}</span>
        </div>

        <div className="rounded-xl border bg-card/90 px-3 py-2 shadow-sm">
          <div className="min-w-0 space-y-1.5">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="break-words text-base font-semibold leading-tight tracking-tight sm:text-lg">
                  {itemHandler.name}
                </h1>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                  {connectedItemCount}{" "}
                  {t("itemHandlers.detail.connections")}
                </Badge>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                  {enabledSkills.length} {t("itemHandlers.detail.skills")}
                </Badge>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                  {enabledMcpServers.length} MCP
                </Badge>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                  {enabledKnowledgeFiles.length}{" "}
                  {t("itemHandlers.detail.knowledge")}
                </Badge>
              </div>
              <p className="max-w-3xl text-[11px] leading-4 text-muted-foreground sm:text-xs">
                {t("itemHandlers.detail.description")}
              </p>
            </div>
          </div>
        </div>
      </section>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-3">
        <div className="overflow-x-auto">
          <div className="flex min-w-max items-center justify-between gap-3">
            <TabsList className="h-auto gap-1 bg-muted/70 p-1">
            <TabsTrigger value="connections">
              {t("itemHandlers.detail.connections")}
            </TabsTrigger>
            <TabsTrigger value="skills">
              {t("itemHandlers.detail.skills")}
            </TabsTrigger>
            <TabsTrigger value="knowledge">
              {t("itemHandlers.detail.knowledge")}
            </TabsTrigger>
            <TabsTrigger value="mcp">MCP</TabsTrigger>
            <TabsTrigger value="config">
              {t("itemHandlers.detail.config")}
            </TabsTrigger>
            </TabsList>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={startEditing}
            >
              {t("itemHandlers.detail.edit")}
            </Button>
          </div>
        </div>

        <TabsContent value="connections">
          {!isConnectionsLoaded ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
                <div className="flex size-12 items-center justify-center rounded-full border bg-muted/40">
                  <Zap className="size-5 text-yellow-500" />
                </div>
                <div>
                  <h2 className="text-base font-semibold">
                    连接图和终端列表按需加载
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    当前已记录 {connectedItemCount} 个连接。点击后再读取全部终端并绘制连接图。
                  </p>
                </div>
                <Button onClick={() => setIsConnectionsLoaded(true)}>
                  加载连接图和终端列表
                </Button>
              </CardContent>
            </Card>
          ) : connectionsLoading ? (
            <Card>
              <CardContent className="flex items-center justify-center gap-2 px-6 py-10 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                正在加载连接图和终端列表...
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="overflow-hidden lg:col-span-2">
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2">
                    <Zap className="size-5 text-yellow-500" />
                    {t("itemHandlers.detail.connectionDiagram")}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {t("itemHandlers.detail.connectionDiagramDescription")}
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <ConnectionDiagram
                    itemHandler={itemHandler}
                    connectedItems={connectedItemsList}
                    availableItems={availableItems}
                    onConnect={handleConnect}
                    onDisconnect={handleDisconnect}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2">
                    <Terminal className="size-5 text-blue-500" />
                    {t("itemHandlers.detail.allItems")}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {t("itemHandlers.detail.allItemsDescription")}
                  </p>
                </CardHeader>
                <CardContent>
                  {allItems.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {t("itemHandlers.detail.noItems")}
                    </p>
                  ) : (
                    <div className="space-y-1">
                      {allItems.map((item: any) => (
                        <ItemWithHandlers
                          key={item.id}
                          item={item}
                          currentHandlerId={itemHandlerId}
                          isConnected={connectedItemIds.has(item.id)}
                        />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="skills">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="size-5 text-yellow-500" />
                {t("itemHandlers.detail.skillsConfiguration")}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {t("itemHandlers.detail.skillsConfigurationDescription")}
              </p>
            </CardHeader>
            <CardContent>
              {skillsLoading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  正在加载技能...
                </div>
              ) : (
                <SkillSelector
                  allSkills={skills}
                  enabledSkills={enabledSkills}
                  onSkillToggle={handleSkillToggle}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="mcp">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Server className="size-5 text-purple-500" />
                {t("itemHandlers.detail.mcpConfiguration")}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {t("itemHandlers.detail.mcpConfigurationDescription")}
              </p>
            </CardHeader>
            <CardContent>
              {mcpLoading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  正在加载 MCP...
                </div>
              ) : (
                <MCPSelector
                  allServers={mcpServers}
                  enabledServers={enabledMcpServers}
                  onServerToggle={handleMcpServerToggle}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="knowledge">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Terminal className="size-5 text-emerald-500" />
                {t("itemHandlers.detail.knowledgeConfiguration")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <KnowledgeBindingSelector
                itemHandlerId={itemHandlerId}
                enabledKnowledgeFiles={enabledKnowledgeFiles}
                onKnowledgeToggle={handleKnowledgeToggle}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="config">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Settings className="size-5" />
                    {t("itemHandlers.detail.modelSettings")}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {t("itemHandlers.detail.modelSettingsDescription")}
                  </p>
                </div>
                <div className="flex gap-2">
                  {!isEditing ? (
                    <Button size="sm" onClick={startEditing}>
                      {t("itemHandlers.detail.edit")}
                    </Button>
                  ) : (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={cancelEditing}
                      >
                        {t("common.cancel")}
                      </Button>
                      <Button
                        size="sm"
                        onClick={saveChanges}
                        disabled={isSaving || !editForm.name.trim()}
                      >
                        {isSaving ? t("common.loading") : t("common.save")}
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {isEditing ? (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        {t("common.name")}
                      </label>
                      <Input
                        value={editForm.name}
                        onChange={(e) =>
                          setEditForm({ ...editForm, name: e.target.value })
                        }
                        aria-invalid={!editForm.name.trim()}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        {t("common.model")}
                      </label>
                      <Input
                        value={editForm.model}
                        onChange={(e) =>
                          setEditForm({ ...editForm, model: e.target.value })
                        }
                        placeholder="e.g., gpt-4"
                      />
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        {t("common.apiKey")}
                      </label>
                      <Input
                        value={editForm.api_key}
                        onChange={(e) =>
                          setEditForm({ ...editForm, api_key: e.target.value })
                        }
                        placeholder={t("common.apiKey")}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">
                        {t("common.apiUrl")}
                      </label>
                      <Input
                        value={editForm.api_url}
                        onChange={(e) =>
                          setEditForm({ ...editForm, api_url: e.target.value })
                        }
                        placeholder={t("common.apiUrl")}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <KeyValue label={t("common.name")} value={itemHandler.name} />
                  <KeyValue
                    label={t("common.model")}
                    value={itemHandler.model}
                  />
                  <KeyValue
                    label={t("common.apiKey")}
                    value={
                      itemHandler.api_key
                        ? `****${itemHandler.api_key.slice(-4)}`
                        : null
                    }
                  />
                  <KeyValue
                    label={t("common.apiUrl")}
                    value={itemHandler.api_url}
                  />
                </div>
              )}
              <div className="border-t pt-4 mt-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <KeyValue label={t("common.id")} value={itemHandler.id} />
                  <KeyValue
                    label={t("common.ownerId")}
                    value={itemHandler.owner_id}
                  />
                  <KeyValue
                    label={t("common.createdAt")}
                    value={
                      formatDate(itemHandler.created_at, localeTag) || undefined
                    }
                  />
                  <KeyValue
                    label={t("common.updatedAt")}
                    value={
                      formatDate(itemHandler.updated_at, localeTag) || undefined
                    }
                  />
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default ItemHandlerDetail
