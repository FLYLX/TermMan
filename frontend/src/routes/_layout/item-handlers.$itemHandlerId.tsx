import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, ChevronRight, Plug, Settings, Terminal, Zap } from "lucide-react"
import { useEffect, useMemo, useRef, useState, useCallback } from "react"
import { ItemHandlersService, ItemHandlerAssociationsService, SkillsService, ItemsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import useCustomToast from "@/hooks/useCustomToast"

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

function formatDate(dateString: string | undefined | null) {
  if (!dateString) return "N/A"
  return new Date(dateString).toLocaleString()
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">{value || "N/A"}</span>
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
  isConnected 
}: { 
  item: any
  currentHandlerId: string
  isConnected: boolean
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [handlers, setHandlers] = useState<any[]>([])

  const { refetch } = useQuery({
    queryFn: () => ItemHandlerAssociationsService.getHandlersForItem({ itemId: item.id }),
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
        <button onClick={toggleExpand} className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded">
          <ChevronRight className={`size-4 text-slate-400 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
        </button>
        <Link
          to="/items/$itemId"
          params={{ itemId: item.id }}
          className="flex items-center gap-2 flex-1 min-w-0"
        >
          <Terminal className="size-4 text-slate-500 shrink-0" />
          <span className="text-sm font-medium truncate">{item.title || item.id}</span>
        </Link>
        {isConnected && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
            Connected
          </span>
        )}
        <span className={`text-xs px-2 py-0.5 rounded-full ${item.status === "running" ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"}`}>
          {item.status === "running" ? "Online" : "Offline"}
        </span>
      </div>
      {isExpanded && (
        <div className="border-t bg-slate-50 dark:bg-slate-900 p-2">
          {handlers.length === 0 ? (
            <p className="text-xs text-muted-foreground px-2">No handlers connected</p>
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
                    <span className="text-xs ml-auto">(current)</span>
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
  const [pendingLine, setPendingLine] = useState<{ startX: number; startY: number; endX: number; endY: number; sourceId: string | null } | null>(null)
  const [isDrawingLine, setIsDrawingLine] = useState(false)
  const [draggingNode, setDraggingNode] = useState<string | null>(null)
  const [nodePositions, setNodePositions] = useState<Record<string, NodePosition>>({})
  const [dragStartPos, setDragStartPos] = useState<{ x: number; y: number } | null>(null)
  const [hasDragged, setHasDragged] = useState(false)

  const connected = useMemo(() => connectedItems || [], [connectedItems])
  const available = useMemo(() => availableItems || [], [availableItems])
  const allItems = useMemo(() => [...connected, ...available], [connected, available])
  const connectedIds = useMemo(() => new Set(connected.map((item) => item.id)), [connected])

  const itemNodeHeight = 40
  const handlerRadius = 45
  const padding = 50
  const calculatedHeight = Math.max(400, allItems.length * 70 + padding * 2 + itemNodeHeight)
  
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
    } else {
      const middleTop = startY + (connectedCount / 2 - 1) * spacing
      const middleBottom = startY + (connectedCount / 2) * spacing
      return (middleTop + middleBottom) / 2
    }
  }, [connected.length, calculatedHeight, padding])
  
  const defaultHandlerPos = useMemo(() => ({ 
    x: 80, 
    y: getHandlerDefaultY()
  }), [getHandlerDefaultY])

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
  }, [allItems.length, calculatedHeight])

  useEffect(() => {
    const itemIds = allItems.map(i => i.id).sort().join(",")
    const nodeHalfHeight = itemNodeHeight / 2
    
    setNodePositions(prev => {
      const newPositions: Record<string, NodePosition> = {}
      const availableHeight = calculatedHeight - padding * 2
      const spacing = Math.min(70, availableHeight / Math.max(allItems.length, 1))
      const totalHeight = (allItems.length - 1) * spacing
      const startY = padding - 20 + (availableHeight - totalHeight) / 2
      
      allItems.forEach((item, index) => {
        if (prev[item.id]) {
          newPositions[item.id] = prev[item.id]
        } else {
          const y = Math.max(padding + nodeHalfHeight, Math.min(calculatedHeight - padding - nodeHalfHeight, startY + index * spacing))
          newPositions[item.id] = { x: 450, y }
        }
      })
      
      return newPositions
    })
  }, [allItems.map(i => i.id).sort().join(","), calculatedHeight])

  const handlerPos = nodePositions["__handler__"] || defaultHandlerPos

  const getItemPos = (itemId: string): NodePosition => {
    return nodePositions[itemId] || { x: 450, y: Math.max(padding + itemNodeHeight / 2, Math.min(calculatedHeight - padding - itemNodeHeight / 2, calculatedHeight / 2)) }
  }

  const startDrawingLine = (e: React.MouseEvent, sourceId: string | null, startX: number, startY: number) => {
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
      const nodeBound = draggingNode === "__handler__" ? handlerRadius : itemNodeHeight / 2
      const newX = Math.max(nodeBound, Math.min(dimensions.width - nodeBound, e.clientX - rect.left))
      const newY = Math.max(nodeBound, Math.min(calculatedHeight - nodeBound, e.clientY - rect.top))
      setNodePositions(prev => ({
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
      <svg
        width="100%"
        height={calculatedHeight}
        className="absolute inset-0"
      >
        <defs>
          <linearGradient id="lineGradient" x1="0%" y1="0%" x2="100%" y2="0%" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.8">
              <animate attributeName="stop-color" values="#60a5fa;#a78bfa;#60a5fa" dur="2s" repeatCount="indefinite" />
            </stop>
            <stop offset="100%" stopColor="#a78bfa" stopOpacity="0.8">
              <animate attributeName="stop-color" values="#a78bfa;#60a5fa;#a78bfa" dur="2s" repeatCount="indefinite" />
            </stop>
          </linearGradient>
          <linearGradient id="pendingLineGradient" x1="0%" y1="0%" x2="100%" y2="0%" gradientUnits="userSpaceOnUse">
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

        <g className={isDrawingLine ? "cursor-pointer" : "cursor-grab active:cursor-grabbing"}>
          <circle
            cx={handlerPos.x}
            cy={handlerPos.y}
            r={45}
            fill={isDrawingLine ? "url(#handlerActiveGradient)" : "url(#handlerGradient)"}
            stroke={isDrawingLine ? "#22c55e" : "#93c5fd"}
            strokeWidth={2}
            onClick={handleHandlerClick}
            onMouseDown={(e) => !isDrawingLine && handleNodeDragStart(e, "__handler__")}
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
            {itemHandler.name.length > 10 ? itemHandler.name.slice(0, 10) + "..." : itemHandler.name}
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
            {isDrawingLine ? "Click item to connect" : `${connected.length} connected`}
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
                className={isDrawingLine && !isConnected ? "cursor-pointer" : "cursor-grab active:cursor-grabbing"}
                onMouseEnter={() => setHoveredItem(item.id)}
                onMouseLeave={() => setHoveredItem(null)}
              >
                <rect
                  x={itemPos.x - 70}
                  y={itemPos.y - 20}
                  width={140}
                  height={40}
                  rx={8}
                  fill={isConnected ? "url(#itemConnectedGradient)" : "url(#itemAvailableGradient)"}
                  stroke={isConnected ? "#22c55e" : isDrawingLine ? "#22c55e" : "#64748b"}
                  strokeWidth={isHovered ? 2 : 1}
                  onClick={(e) => handleItemClick(e, item.id)}
                  onMouseDown={(e) => !isDrawingLine && handleNodeDragStart(e, item.id)}
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
                  {item.title.length > 12 ? item.title.slice(0, 12) + "..." : item.title}
                </text>
                <text
                  x={itemPos.x - 45}
                  y={itemPos.y + 8}
                  fill={isConnected ? "#93c5fd" : isDrawingLine ? "#22c55e" : "#94a3b8"}
                  fontSize="8"
                  pointerEvents="none"
                >
                  {isConnected ? "Connected" : isDrawingLine ? "Click to connect" : "Click to draw line"}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      <div className="absolute top-4 left-4 flex items-center gap-2">
        <Badge variant="outline" className="bg-sky-500/20 border-sky-500/50 text-sky-300">
          {connected.length} Connected
        </Badge>
        <Badge variant="outline" className="bg-green-500/20 border-green-500/50 text-green-300">
          {available.length} Available
        </Badge>
      </div>

      <div className="absolute bottom-4 left-4 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-green-500" /> Running
        </span>
        <span className="flex items-center gap-1 mt-1">
          <span className="inline-block w-2 h-2 rounded-full bg-slate-500" /> Stopped
        </span>
      </div>
    </div>
  )
}

function ItemHandlerDetail() {
  const { itemHandlerId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [isSaving, setIsSaving] = useState(false)
  const [connectingItemId, setConnectingItemId] = useState<string | null>(null)

  const { data: itemHandler, isLoading } = useQuery({
    ...getItemHandlerQueryOptions(itemHandlerId),
  })

  const { data: connectedItems } = useQuery({
    queryFn: () => ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: ["itemHandler-items", itemHandlerId],
  })

  const { data: allItemsData } = useQuery({
    queryFn: () => ItemsService.readItems(),
    queryKey: ["items"],
  })

  const { data: skillsData } = useQuery({
    queryKey: ["skills"],
    queryFn: () => SkillsService.listSkills({}),
  })

  const allItems = (allItemsData as any)?.data || []
  const connectedItemsList = (connectedItems as any[]) || []
  const connectedItemIds = new Set(connectedItemsList.map((item: any) => item.id))
  const availableItems = allItems.filter((item: any) => !connectedItemIds.has(item.id))

  const skills = skillsData?.data || []
  const enabledSkills = (itemHandler as any)?.enabled_skills ?? []

  const [editForm, setEditForm] = useState({
    name: "",
    model: "",
    api_key: "",
    api_url: "",
    enabled_skills: [] as string[],
  })

  const [isEditing, setIsEditing] = useState(false)

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
    }
  }

  const cancelEditing = () => {
    setIsEditing(false)
  }

  const saveChanges = async () => {
    setIsSaving(true)
    try {
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody: editForm,
      })
      showSuccessToast("ItemHandler updated successfully")
      setIsEditing(false)
      queryClient.invalidateQueries({ queryKey: ["itemHandler", itemHandlerId] })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
    } catch (error) {
      showErrorToast("Failed to update ItemHandler")
    } finally {
      setIsSaving(false)
    }
  }

  const toggleSkill = (skillId: string) => {
    const current = editForm.enabled_skills
    if (current.includes(skillId)) {
      setEditForm({ ...editForm, enabled_skills: current.filter((s) => s !== skillId) })
    } else {
      setEditForm({ ...editForm, enabled_skills: [...current, skillId] })
    }
  }

  const handleConnect = async (itemId: string) => {
    setConnectingItemId(itemId)
    try {
      await ItemHandlerAssociationsService.addItemToHandler({
        requestBody: {
          item_handler_id: itemHandlerId,
          item_id: itemId,
        },
      })
      showSuccessToast("Item connected successfully")
      queryClient.invalidateQueries({ queryKey: ["itemHandler-items", itemHandlerId] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    } catch (error) {
      showErrorToast("Failed to connect item")
    } finally {
      setConnectingItemId(null)
    }
  }

  const handleDisconnect = async (itemId: string) => {
    try {
      await ItemHandlerAssociationsService.removeItemFromHandler({
        itemHandlerId: itemHandlerId,
        itemId: itemId,
      })
      showSuccessToast("Item disconnected")
      queryClient.invalidateQueries({ queryKey: ["itemHandler-items", itemHandlerId] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    } catch (error) {
      showErrorToast("Failed to disconnect item")
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    )
  }

  if (!itemHandler) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground">ItemHandler not found</div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-6">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Link to="/item-handlers" className="hover:text-foreground">
            Item Handlers
          </Link>
          <ChevronRight className="size-4" />
          <span className="text-foreground">{itemHandler.name}</span>
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
                <Link to="/item-handlers">
                  <ArrowLeft className="size-4" />
                  Back to item handlers
                </Link>
              </Button>

              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <div className="flex size-12 items-center justify-center rounded-xl border bg-muted/40">
                  <Settings className="size-6 text-muted-foreground" />
                </div>

                <div className="space-y-3">
                  <h1 className="text-3xl font-bold tracking-tight">
                    {itemHandler.name}
                  </h1>
                  <p className="max-w-3xl text-sm text-muted-foreground">
                    Manage item handler configuration and associated items
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {!isEditing ? (
                <Button onClick={startEditing}>Edit</Button>
              ) : (
                <>
                  <Button variant="outline" onClick={cancelEditing}>
                    Cancel
                  </Button>
                  <Button onClick={saveChanges} disabled={isSaving}>
                    {isSaving ? "Saving..." : "Save"}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Zap className="size-5 text-yellow-500" />
              Connection Diagram
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Visual representation of items managed by this handler
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
              All Items
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Click to expand and view connected handlers
            </p>
          </CardHeader>
          <CardContent>
            {allItems.length === 0 ? (
              <p className="text-sm text-muted-foreground">No items available</p>
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

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Basic Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {isEditing ? (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Name</label>
                  <Input
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Model</label>
                  <Input
                    value={editForm.model}
                    onChange={(e) => setEditForm({ ...editForm, model: e.target.value })}
                    placeholder="e.g., gpt-4"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">API Key</label>
                  <Input
                    value={editForm.api_key}
                    onChange={(e) => setEditForm({ ...editForm, api_key: e.target.value })}
                    placeholder="API key for the model"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">API URL</label>
                  <Input
                    value={editForm.api_url}
                    onChange={(e) => setEditForm({ ...editForm, api_url: e.target.value })}
                    placeholder="https://api.example.com"
                  />
                </div>
              </>
            ) : (
              <div className="grid gap-3">
                <KeyValue label="ID" value={itemHandler.id} />
                <KeyValue label="Name" value={itemHandler.name} />
                <KeyValue label="Model" value={itemHandler.model} />
                <KeyValue label="API Key" value={itemHandler.api_key ? `****${itemHandler.api_key.slice(-4)}` : null} />
                <KeyValue label="API URL" value={itemHandler.api_url} />
                <KeyValue label="Owner ID" value={itemHandler.owner_id} />
                <KeyValue label="Created At" value={formatDate(itemHandler.created_at)} />
                <KeyValue label="Updated At" value={formatDate(itemHandler.updated_at)} />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Terminal className="size-5" />
              Enabled Skills
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isEditing ? (
              <ScrollArea className="h-64">
                <div className="space-y-3">
                  {skills.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No skills available</p>
                  ) : (
                    skills.map((skill: any) => (
                      <div key={skill.skill_id} className="flex items-center space-x-2">
                        <Checkbox
                          id={skill.skill_id}
                          checked={editForm.enabled_skills.includes(skill.skill_id)}
                          onCheckedChange={() => toggleSkill(skill.skill_id)}
                        />
                        <label htmlFor={skill.skill_id} className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                          {skill.name}
                        </label>
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            ) : (
              <ScrollArea className="h-64">
                {enabledSkills.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No skills enabled</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {enabledSkills.map((skillId: string) => {
                      const skill = skills.find((s) => s.skill_id === skillId)
                      return (
                        <Badge key={skillId} variant="secondary">
                          {skill?.name || skillId}
                        </Badge>
                      )
                    })}
                  </div>
                )}
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default ItemHandlerDetail
