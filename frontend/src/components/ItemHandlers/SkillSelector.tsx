import { useEffect, useMemo, useState } from "react"
import { GripVertical, Loader2, Search, Terminal, X, Zap } from "lucide-react"

import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { LIST_PAGE_SIZE, LoadMoreButton } from "@/components/ItemHandlers/dispatcherShared"

export function SkillSelector({
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
  const [enabledVisibleCount, setEnabledVisibleCount] = useState(LIST_PAGE_SIZE)
  const [availableVisibleCount, setAvailableVisibleCount] =
    useState(LIST_PAGE_SIZE)

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
  const visibleEnabledSkills = enabledSkillsList.slice(0, enabledVisibleCount)
  const visibleAvailableSkills = filteredAvailableSkills.slice(
    0,
    availableVisibleCount,
  )
  const enabledRemainingCount = Math.max(
    enabledSkillsList.length - visibleEnabledSkills.length,
    0,
  )
  const availableRemainingCount = Math.max(
    filteredAvailableSkills.length - visibleAvailableSkills.length,
    0,
  )

  useEffect(() => {
    setEnabledVisibleCount(LIST_PAGE_SIZE)
  }, [enabledSkillsList.length])

  useEffect(() => {
    setAvailableVisibleCount(LIST_PAGE_SIZE)
  }, [availableSkillsList.length, searchQuery])

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
              {visibleEnabledSkills.map((skill) => (
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
              {visibleAvailableSkills.map((skill) => (
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
