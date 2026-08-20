import { Loader2, Sparkles } from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { apiRequest } from "@/lib/api-request"

import type { FilterRule } from "./FilterRuleEditor"
import { SketchDialog } from "./SketchDialog"

type FilterTarget = "input" | "output"

type FilterGenerationResponse = {
  success: boolean
  target: FilterTarget
  rules: Record<string, FilterRule>
  explanation: string
  item_handler_id: string
  model: string
}

interface FilterGeneratorDialogProps {
  itemId: string
  target: FilterTarget
  currentRules: Record<string, FilterRule>
  onApply: (rules: Record<string, FilterRule>) => void
}

export function FilterGeneratorDialog({
  itemId,
  target,
  currentRules,
  onApply,
}: FilterGeneratorDialogProps) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [instruction, setInstruction] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedRules, setGeneratedRules] = useState<Record<
    string,
    FilterRule
  > | null>(null)
  const [explanation, setExplanation] = useState("")
  const [model, setModel] = useState("")
  const targetMeta =
    target === "input"
      ? {
          flow: "Terminal output -> Agent",
          promptLabel: "描述你想要的过滤效果（终端输出 → Agent）",
          placeholder:
            "例如：忽略进度条、把 error 提示标记为需关注、给 access token 打码。",
        }
      : {
          flow: "Agent command -> terminal",
          promptLabel: "描述你想要的过滤效果（Agent 命令 → 终端）",
          placeholder:
            "例如：拦截 rm -rf 等危险命令、记录 sudo 使用、执行前给密码打码。",
        }

  const previewJson = useMemo(() => {
    if (!generatedRules) {
      return ""
    }
    return JSON.stringify(generatedRules, null, 2)
  }, [generatedRules])

  const handleGenerate = async () => {
    if (!instruction.trim()) {
      showErrorToast("先描述要生成的过滤规则")
      return
    }

    setIsGenerating(true)
    try {
      const result = await apiRequest<FilterGenerationResponse>(
        `/api/v1/items/${itemId}/generate-filter`,
        {
          method: "POST",
          body: JSON.stringify({
            target,
            instruction,
            existing_rules: currentRules,
          }),
        },
      )
      setGeneratedRules(result.rules)
      setExplanation(result.explanation || "")
      setModel(result.model || "")
      showSuccessToast("规则已生成")
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Failed to generate filter",
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const handleApply = () => {
    if (!generatedRules) {
      return
    }
    onApply(generatedRules)
    showSuccessToast("已应用到编辑器")
    setOpen(false)
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setOpen(true)}
      >
        <Sparkles className="mr-2 size-4" />
        LLM 生成
      </Button>
      <SketchDialog
        open={open}
        onClose={() => setOpen(false)}
        title={
          <span className="flex items-center gap-2">
            用 LLM 生成过滤规则
            <Badge variant="outline" className="text-[10px] uppercase">
              {targetMeta.flow}
            </Badge>
            {model && (
              <Badge variant="secondary" className="text-[10px]">
                {model}
              </Badge>
            )}
          </span>
        }
        description="生成结果预览确认后再应用，应用会自动保存。"
      >
        <div className="space-y-3">
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">
              {targetMeta.promptLabel}
            </Label>
            <Textarea
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              placeholder={targetMeta.placeholder}
              className="min-h-24 text-sm"
            />
          </div>

          <Button
            type="button"
            size="sm"
            onClick={handleGenerate}
            disabled={isGenerating}
            className="w-full"
          >
            {isGenerating ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 size-4" />
            )}
            生成
          </Button>

          {explanation && (
            <p className="text-xs text-muted-foreground">{explanation}</p>
          )}

          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">
              生成结果预览
            </Label>
            <Textarea
              readOnly
              value={previewJson}
              placeholder="生成的规则会显示在这里"
              className="min-h-48 font-mono text-xs"
            />
          </div>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleApply}
            disabled={!generatedRules}
            className="w-full"
          >
            应用到编辑器
          </Button>
        </div>
      </SketchDialog>
    </>
  )
}
