import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  FileText,
  GripVertical,
  Loader2,
  Search,
  Settings,
  X,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import useCustomToast from "@/hooks/useCustomToast"

import {
  formatBytes,
  getItemHandlerKnowledgeQueryKey,
  listItemHandlerKnowledgeFiles,
} from "./api"

const LIST_PAGE_SIZE = 10

function LoadMoreButton({
  remainingCount,
  onClick,
}: {
  remainingCount: number
  onClick: () => void
}) {
  const { locale } = useI18n()
  const nextCount = Math.min(LIST_PAGE_SIZE, remainingCount)

  if (remainingCount <= 0) {
    return null
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="w-full"
      onClick={onClick}
    >
      {locale === "zh"
        ? `再显示 ${nextCount} 条`
        : `Show ${nextCount} more`}
    </Button>
  )
}

export function KnowledgeBindingSelector({
  itemHandlerId,
  enabledKnowledgeFiles,
  onKnowledgeToggle,
}: {
  itemHandlerId: string
  enabledKnowledgeFiles: string[]
  onKnowledgeToggle: (filePath: string, enable: boolean) => Promise<void>
}) {
  const { t } = useI18n()
  const { showErrorToast } = useCustomToast()

  const [searchQuery, setSearchQuery] = useState("")
  const [draggedPath, setDraggedPath] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<"enabled" | "available" | null>(
    null,
  )
  const [pendingPath, setPendingPath] = useState<string | null>(null)
  const [enabledVisibleCount, setEnabledVisibleCount] =
    useState(LIST_PAGE_SIZE)
  const [availableVisibleCount, setAvailableVisibleCount] =
    useState(LIST_PAGE_SIZE)

  const { data: knowledgeFilesData } = useQuery({
    queryKey: getItemHandlerKnowledgeQueryKey(itemHandlerId),
    queryFn: () => listItemHandlerKnowledgeFiles(itemHandlerId),
  })

  const knowledgeFiles = knowledgeFilesData?.data ?? []

  const enabledFilesList = useMemo(() => {
    return knowledgeFiles.filter((file) => file.enabled)
  }, [knowledgeFiles])

  const availableFilesList = useMemo(() => {
    return knowledgeFiles.filter((file) => !file.enabled)
  }, [knowledgeFiles])

  const filteredAvailableFiles = useMemo(() => {
    if (!searchQuery) {
      return availableFilesList
    }

    const normalizedQuery = searchQuery.toLowerCase()
    return availableFilesList.filter(
      (file) =>
        file.name.toLowerCase().includes(normalizedQuery) ||
        file.path.toLowerCase().includes(normalizedQuery),
    )
  }, [availableFilesList, searchQuery])
  const visibleEnabledFiles = enabledFilesList.slice(0, enabledVisibleCount)
  const visibleAvailableFiles = filteredAvailableFiles.slice(
    0,
    availableVisibleCount,
  )
  const enabledRemainingCount = Math.max(
    enabledFilesList.length - visibleEnabledFiles.length,
    0,
  )
  const availableRemainingCount = Math.max(
    filteredAvailableFiles.length - visibleAvailableFiles.length,
    0,
  )

  useEffect(() => {
    setEnabledVisibleCount(LIST_PAGE_SIZE)
  }, [enabledFilesList.length])

  useEffect(() => {
    setAvailableVisibleCount(LIST_PAGE_SIZE)
  }, [availableFilesList.length, searchQuery])

  const updateEnabledFiles = async (filePath: string, enable: boolean) => {
    setPendingPath(filePath)
    try {
      await onKnowledgeToggle(filePath, enable)
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : t("itemHandlers.detail.knowledgeUpdateFailed"),
      )
    } finally {
      setPendingPath(null)
    }
  }

  const handleDrop = async (
    event: React.DragEvent<HTMLDivElement>,
    target: "enabled" | "available",
  ) => {
    event.preventDefault()
    setDropTarget(null)

    if (!draggedPath) {
      return
    }

    const isCurrentlyEnabled = enabledKnowledgeFiles.includes(draggedPath)
    if (target === "enabled" && !isCurrentlyEnabled) {
      await updateEnabledFiles(draggedPath, true)
    } else if (target === "available" && isCurrentlyEnabled) {
      await updateEnabledFiles(draggedPath, false)
    }

    setDraggedPath(null)
  }

  const renderFileRow = (
    file: (typeof knowledgeFiles)[number],
    enabled: boolean,
  ) => {
    const isPending = pendingPath === file.path
    const baseClass = enabled
      ? "bg-emerald-50 border-emerald-200 dark:bg-emerald-950/30 dark:border-emerald-800"
      : "bg-muted/50 border-border hover:bg-muted"
    const missingClass = file.missing
      ? "border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/20"
      : ""

    return (
      <div
        key={file.path}
        draggable
        onDragStart={() => setDraggedPath(file.path)}
        onDragEnd={() => {
          setDraggedPath(null)
          setDropTarget(null)
        }}
        onClick={() => {
          if (!enabled) {
            void updateEnabledFiles(file.path, true)
          }
        }}
        className={`flex items-center gap-2 rounded-md border px-3 py-2 transition-all ${baseClass} ${missingClass} ${draggedPath === file.path ? "scale-95 opacity-60" : ""} ${enabled ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}`}
      >
        {isPending ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <GripVertical className="size-4 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="size-4 shrink-0 text-slate-500" />
            <span className="truncate text-sm font-medium">{file.name}</span>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {file.path}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{formatBytes(file.size)}</span>
            {file.indexed && (
              <Badge variant="outline">
                {t("itemHandlers.detail.knowledgeIndexed")}
              </Badge>
            )}
            {file.missing && (
              <Badge variant="destructive">
                {t("itemHandlers.detail.knowledgeMissing")}
              </Badge>
            )}
            {file.chunk_count > 0 && <span>{file.chunk_count} chunks</span>}
          </div>
        </div>
        {enabled && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              void updateEnabledFiles(file.path, false)
            }}
            className="rounded p-1 hover:bg-emerald-100 dark:hover:bg-emerald-900"
          >
            <X className="size-3 text-emerald-700 dark:text-emerald-300" />
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          {t("itemHandlers.detail.knowledgeConfigurationDescription")}
        </div>
        <Button asChild type="button" variant="outline">
          <Link to="/knowledge">
            <Settings className="mr-2 size-4" />
            {t("itemHandlers.detail.manageKnowledgeFiles")}
          </Link>
        </Button>
      </div>

      <div className="grid h-80 gap-4 lg:grid-cols-2">
        <div
          className={`flex flex-col overflow-hidden rounded-lg border transition-colors ${
            dropTarget === "enabled"
              ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20"
              : "border-border"
          }`}
          onDragOver={(event) => {
            event.preventDefault()
            setDropTarget("enabled")
          }}
          onDragLeave={() => setDropTarget(null)}
          onDrop={(event) => void handleDrop(event, "enabled")}
        >
          <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-emerald-500" />
              <span className="text-sm font-medium">
                {t("itemHandlers.detail.enabledKnowledge", {
                  count: enabledFilesList.length,
                })}
              </span>
            </div>
          </div>
          <ScrollArea className="flex-1">
            {enabledFilesList.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center p-4 text-muted-foreground">
                <GripVertical className="mb-2 size-8 opacity-30" />
                <p className="text-center text-sm">
                  {t("itemHandlers.detail.dropKnowledgeHere")}
                </p>
              </div>
            ) : (
              <div className="space-y-1 p-2">
                {visibleEnabledFiles.map((file) => renderFileRow(file, true))}
                <LoadMoreButton
                  remainingCount={enabledRemainingCount}
                  onClick={() =>
                    setEnabledVisibleCount(
                      (current) => current + LIST_PAGE_SIZE,
                    )
                  }
                />
              </div>
            )}
          </ScrollArea>
        </div>

        <div
          className={`flex flex-col overflow-hidden rounded-lg border transition-colors ${
            dropTarget === "available"
              ? "border-blue-500 bg-blue-50/50 dark:bg-blue-950/20"
              : "border-border"
          }`}
          onDragOver={(event) => {
            event.preventDefault()
            setDropTarget("available")
          }}
          onDragLeave={() => setDropTarget(null)}
          onDrop={(event) => void handleDrop(event, "available")}
        >
          <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-blue-500" />
              <span className="text-sm font-medium">
                {t("itemHandlers.detail.availableKnowledge", {
                  count: availableFilesList.length,
                })}
              </span>
            </div>
          </div>
          <div className="border-b px-3 py-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={t("itemHandlers.detail.searchKnowledge")}
                className="h-8 pl-8"
              />
            </div>
          </div>
          <ScrollArea className="flex-1">
            {filteredAvailableFiles.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center p-4 text-muted-foreground">
                <Search className="mb-2 size-8 opacity-30" />
                <p className="text-center text-sm">
                  {knowledgeFiles.length === 0
                    ? t("itemHandlers.detail.noKnowledgeFiles")
                    : searchQuery
                      ? t("itemHandlers.detail.noMatchingKnowledge")
                      : t("itemHandlers.detail.noKnowledgeFiles")}
                </p>
              </div>
            ) : (
              <div className="space-y-1 p-2">
                {visibleAvailableFiles.map((file) =>
                  renderFileRow(file, false),
                )}
                <LoadMoreButton
                  remainingCount={availableRemainingCount}
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
    </div>
  )
}
