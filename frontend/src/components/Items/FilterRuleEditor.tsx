import {
  ChevronDown,
  ChevronRight,
  Code,
  GripVertical,
  List,
  Plus,
  Trash2,
} from "lucide-react"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

export interface FilterRule {
  name?: string
  regex_patterns: string[]
  action_type: "block" | "ignore" | "log" | "replace"
  reason?: string
  action?: {
    replace_rules: Record<string, string>
  }
}

interface FilterRuleEditorProps {
  value: Record<string, FilterRule>
  onChange: (value: Record<string, FilterRule>) => void
  defaultRules: Record<string, FilterRule>
}

const ACTION_TYPE_LABELS: Record<
  string,
  {
    label: string
    description: string
    variant: "destructive" | "default" | "secondary" | "outline"
  }
> = {
  block: {
    label: "拦截",
    description: "匹配后拦截，不输出",
    variant: "destructive",
  },
  ignore: {
    label: "忽略",
    description: "匹配后忽略，标记为噪音",
    variant: "secondary",
  },
  log: {
    label: "输出",
    description: "匹配后输出，标记为需关注",
    variant: "default",
  },
  replace: { label: "替换", description: "匹配后替换内容", variant: "outline" },
}

export function FilterRuleEditor({
  value,
  onChange,
  defaultRules,
}: FilterRuleEditorProps) {
  const [mode, setMode] = useState<"ui" | "json">("ui")
  const [jsonText, setJsonText] = useState("")
  const [jsonError, setJsonError] = useState("")
  const [expandedFilters, setExpandedFilters] = useState<Set<number>>(new Set())
  const [filters, setFilters] = useState<FilterRule[]>(() =>
    Object.entries(value || {}).map(([name, rule]) => ({ ...rule, name })),
  )

  useEffect(() => {
    if (mode === "ui") {
      const newFilters = Object.entries(value || {}).map(([name, rule]) => ({
        ...rule,
        name,
      }))
      setFilters(newFilters)
    }
  }, [value, mode])

  useEffect(() => {
    if (mode === "json") {
      setJsonText(JSON.stringify(value, null, 2))
    }
  }, [value, mode])

  const toggleFilter = (index: number) => {
    const newExpanded = new Set(expandedFilters)
    if (newExpanded.has(index)) {
      newExpanded.delete(index)
    } else {
      newExpanded.add(index)
    }
    setExpandedFilters(newExpanded)
  }

  const emitChange = (newFilters: FilterRule[]) => {
    const result: Record<string, FilterRule> = {}
    newFilters.forEach((f) => {
      const { name, ...rule } = f
      if (name) {
        result[name] = rule
      }
    })
    onChange(result)
  }

  const addFilter = () => {
    const newFilter: FilterRule = {
      name: `filter_${Date.now()}`,
      regex_patterns: [""],
      action_type: "ignore",
    }
    const newFilters = [...filters, newFilter]
    setFilters(newFilters)
    setExpandedFilters(new Set([...expandedFilters, newFilters.length - 1]))
    emitChange(newFilters)
  }

  const removeFilter = (index: number) => {
    const newFilters = filters.filter((_, i) => i !== index)
    setFilters(newFilters)
    const newExpanded = new Set(expandedFilters)
    newExpanded.delete(index)
    setExpandedFilters(newExpanded)
    emitChange(newFilters)
  }

  const updateFilter = (index: number, updates: Partial<FilterRule>) => {
    const newFilters = filters.map((f, i) =>
      i === index ? { ...f, ...updates } : f,
    )
    setFilters(newFilters)
    emitChange(newFilters)
  }

  const updatePattern = (
    filterIndex: number,
    patternIndex: number,
    value: string,
  ) => {
    const newPatterns = [...filters[filterIndex].regex_patterns]
    newPatterns[patternIndex] = value
    updateFilter(filterIndex, { regex_patterns: newPatterns })
  }

  const addPattern = (filterIndex: number) => {
    const newPatterns = [...filters[filterIndex].regex_patterns, ""]
    updateFilter(filterIndex, { regex_patterns: newPatterns })
  }

  const removePattern = (filterIndex: number, patternIndex: number) => {
    const newPatterns = filters[filterIndex].regex_patterns.filter(
      (_, i) => i !== patternIndex,
    )
    updateFilter(filterIndex, { regex_patterns: newPatterns })
  }

  const updateReplaceRule = (
    filterIndex: number,
    pattern: string,
    replacement: string,
  ) => {
    const filter = filters[filterIndex]
    const replaceRules = filter.action?.replace_rules || {}
    const newReplaceRules = { ...replaceRules, [pattern]: replacement }
    updateFilter(filterIndex, {
      action: { replace_rules: newReplaceRules },
    })
  }

  const handleJsonChange = (text: string) => {
    setJsonText(text)
    setJsonError("")

    try {
      if (text.trim()) {
        const parsed = JSON.parse(text)
        const newFilters: FilterRule[] = []

        for (const [name, config] of Object.entries(parsed)) {
          if (typeof config === "object" && config !== null) {
            const cfg = config as Record<string, unknown>
            newFilters.push({
              name,
              regex_patterns: Array.isArray(cfg.regex_patterns)
                ? (cfg.regex_patterns as string[])
                : [],
              action_type:
                (cfg.action_type as FilterRule["action_type"]) || "ignore",
              reason: typeof cfg.reason === "string" ? cfg.reason : undefined,
              action: cfg.action as FilterRule["action"],
            })
          }
        }

        setFilters(newFilters)
        onChange(parsed as Record<string, FilterRule>)
      }
    } catch (_e) {
      setJsonError("JSON 格式错误")
    }
  }

  const loadDefaultRules = () => {
    const newFilters = Object.entries(defaultRules).map(([name, rule]) => ({
      ...rule,
      name,
    }))
    setFilters(newFilters)
    setExpandedFilters(new Set())
    onChange(defaultRules)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={mode === "ui" ? "default" : "outline"}
            onClick={() => setMode("ui")}
          >
            <List className="size-4 mr-1" />
            UI 模式
          </Button>
          <Button
            size="sm"
            variant={mode === "json" ? "default" : "outline"}
            onClick={() => setMode("json")}
          >
            <Code className="size-4 mr-1" />
            JSON 模式
          </Button>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={loadDefaultRules}>
            加载默认规则
          </Button>
          {mode === "ui" && (
            <Button size="sm" onClick={addFilter}>
              <Plus className="size-4 mr-1" />
              添加过滤器
            </Button>
          )}
        </div>
      </div>

      {mode === "json" ? (
        <div className="space-y-2">
          <Textarea
            placeholder={`{
  "filter_name": {
    "regex_patterns": ["pattern1", "pattern2"],
    "action_type": "block|ignore|log|replace",
    "action": {
      "replace_rules": {"pattern": "replacement"}
    }
  }
}`}
            className="font-mono text-xs min-h-[400px]"
            value={jsonText}
            onChange={(e) => handleJsonChange(e.target.value)}
          />
          {jsonError && <p className="text-xs text-red-500">{jsonError}</p>}
          <p className="text-xs text-muted-foreground">
            粘贴 JSON 后自动解析生成 UI
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filters.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              暂无过滤器，点击"添加过滤器"或"加载默认规则"
            </div>
          ) : (
            filters.map((filter, filterIndex) => (
              <Collapsible
                key={filterIndex}
                open={expandedFilters.has(filterIndex)}
                onOpenChange={() => toggleFilter(filterIndex)}
                className="border rounded-lg overflow-hidden"
              >
                <CollapsibleTrigger asChild>
                  <div
                    className={`flex items-center gap-2 p-3 cursor-pointer transition-colors ${
                      filter.action_type === "block"
                        ? "bg-red-50 hover:bg-red-100 dark:bg-red-950/30 dark:hover:bg-red-950/50"
                        : filter.action_type === "ignore"
                          ? "bg-gray-50 hover:bg-gray-100 dark:bg-gray-950/30 dark:hover:bg-gray-950/50"
                          : filter.action_type === "log"
                            ? "bg-blue-50 hover:bg-blue-100 dark:bg-blue-950/30 dark:hover:bg-blue-950/50"
                            : "bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/30 dark:hover:bg-amber-950/50"
                    }`}
                  >
                    <div className="flex items-center gap-1 flex-1">
                      {expandedFilters.has(filterIndex) ? (
                        <ChevronDown className="size-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="size-4 text-muted-foreground" />
                      )}
                      <GripVertical className="size-4 text-muted-foreground cursor-grab" />
                      <span className="font-medium">{filter.name}</span>
                      <span
                        className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
                          filter.action_type === "block"
                            ? "bg-red-500 text-white"
                            : filter.action_type === "ignore"
                              ? "bg-gray-500 text-white"
                              : filter.action_type === "log"
                                ? "bg-blue-500 text-white"
                                : "bg-amber-500 text-white"
                        }`}
                      >
                        {ACTION_TYPE_LABELS[filter.action_type].label}
                      </span>
                      <span className="text-xs text-muted-foreground ml-2">
                        ({filter.regex_patterns.length} 条规则)
                      </span>
                      {filter.reason ? (
                        <span className="hidden truncate text-xs text-muted-foreground md:inline">
                          {filter.reason}
                        </span>
                      ) : null}
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFilter(filterIndex)
                      }}
                      className="text-destructive hover:text-destructive shrink-0"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="p-4 space-y-4 border-t">
                    <div className="grid gap-3 sm:grid-cols-[240px_minmax(0,1fr)]">
                      <div className="space-y-1.5">
                        <Label className="text-xs">过滤器名称</Label>
                        <Input
                          value={filter.name}
                          onChange={(e) =>
                            updateFilter(filterIndex, { name: e.target.value })
                          }
                          placeholder="过滤器名称"
                        />
                      </div>
                      <div className="min-w-0 space-y-1.5">
                        <Label className="text-xs">说明</Label>
                        <Input
                          value={filter.reason || ""}
                          onChange={(e) =>
                            updateFilter(filterIndex, {
                              reason: e.target.value || undefined,
                            })
                          }
                          placeholder="为什么添加这条规则"
                        />
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">处理方式</Label>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(ACTION_TYPE_LABELS).map(
                          ([type, info]) => (
                            <button
                              key={type}
                              type="button"
                              title={info.description}
                              onClick={() =>
                                updateFilter(filterIndex, {
                                  action_type:
                                    type as FilterRule["action_type"],
                                })
                              }
                              className={`px-4 py-2 text-sm rounded-md transition-all ${
                                filter.action_type === type
                                  ? type === "block"
                                    ? "bg-red-500 text-white shadow-sm"
                                    : type === "ignore"
                                      ? "bg-gray-500 text-white shadow-sm"
                                      : type === "log"
                                        ? "bg-blue-500 text-white shadow-sm"
                                        : "bg-amber-500 text-white shadow-sm"
                                  : "bg-muted hover:bg-muted/80"
                              }`}
                            >
                              {info.label}
                            </button>
                          ),
                        )}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">正则表达式</Label>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => addPattern(filterIndex)}
                        >
                          <Plus className="size-3 mr-1" />
                          添加
                        </Button>
                      </div>
                      {filter.regex_patterns.map((pattern, patternIndex) => (
                        <div key={patternIndex} className="flex gap-2">
                          <Input
                            value={pattern}
                            onChange={(e) =>
                              updatePattern(
                                filterIndex,
                                patternIndex,
                                e.target.value,
                              )
                            }
                            placeholder="正则表达式"
                            className="font-mono text-xs flex-1"
                          />
                          {filter.regex_patterns.length > 1 && (
                            <Button
                              size="icon"
                              variant="ghost"
                              onClick={() =>
                                removePattern(filterIndex, patternIndex)
                              }
                              className="text-destructive hover:text-destructive shrink-0"
                            >
                              <Trash2 className="size-3" />
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>

                    {filter.action_type === "replace" && (
                      <div className="space-y-2">
                        <Label className="text-xs">替换规则</Label>
                        {filter.regex_patterns
                          .filter((p) => p)
                          .map((pattern) => (
                            <div
                              key={pattern}
                              className="flex gap-2 items-center"
                            >
                              <Input
                                value={pattern}
                                disabled
                                className="font-mono text-xs flex-1 bg-muted"
                              />
                              <span className="text-muted-foreground">→</span>
                              <Input
                                value={
                                  filter.action?.replace_rules?.[pattern] || ""
                                }
                                onChange={(e) =>
                                  updateReplaceRule(
                                    filterIndex,
                                    pattern,
                                    e.target.value,
                                  )
                                }
                                placeholder="替换为"
                                className="flex-1"
                              />
                            </div>
                          ))}
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            ))
          )}
        </div>
      )}
    </div>
  )
}
