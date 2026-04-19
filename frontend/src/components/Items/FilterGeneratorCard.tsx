import { Loader2, Sparkles } from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { apiRequest } from "@/lib/api-request"

import type { FilterRule } from "./FilterRuleEditor"

type FilterTarget = "input" | "output"

type FilterGenerationResponse = {
  success: boolean
  target: FilterTarget
  rules: Record<string, FilterRule>
  explanation: string
  item_handler_id: string
  model: string
}

interface FilterGeneratorCardProps {
  itemId: string
  target: FilterTarget
  currentRules: Record<string, FilterRule>
  onApply: (rules: Record<string, FilterRule>) => void
}

export function FilterGeneratorCard({
  itemId,
  target,
  currentRules,
  onApply,
}: FilterGeneratorCardProps) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [instruction, setInstruction] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedRules, setGeneratedRules] = useState<Record<
    string,
    FilterRule
  > | null>(null)
  const [explanation, setExplanation] = useState("")
  const [model, setModel] = useState("")

  const previewJson = useMemo(() => {
    if (!generatedRules) {
      return ""
    }
    return JSON.stringify(generatedRules, null, 2)
  }, [generatedRules])

  const handleGenerate = async () => {
    if (!instruction.trim()) {
      showErrorToast("Describe the filter you want to generate first")
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
      showSuccessToast("Generated filter JSON")
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
    showSuccessToast("Applied generated filter JSON to the editor")
  }

  return (
    <div className="mb-4 rounded-xl border border-dashed bg-muted/20 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-amber-500" />
            <span className="text-sm font-medium">Generate With LLM</span>
            <Badge variant="outline" className="text-[10px] uppercase">
              {target}
            </Badge>
            {model && (
              <Badge variant="secondary" className="text-[10px]">
                {model}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Describe the patterns you want. The generated JSON will be loaded
            into the filter editor after you apply it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            {isGenerating ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 size-4" />
            )}
            Generate
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleApply}
            disabled={!generatedRules}
          >
            Apply JSON
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">
            Prompt for {target} filter
          </Label>
          <Textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder={
              target === "input"
                ? "Example: ignore progress bars, log error prompts, redact access tokens."
                : "Example: block destructive disk commands, log sudo usage, redact passwords."
            }
            className="min-h-32 text-sm"
          />
          {explanation && (
            <p className="text-xs text-muted-foreground">{explanation}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">
            Generated JSON preview
          </Label>
          <Textarea
            readOnly
            value={previewJson}
            placeholder="Generated rules will appear here."
            className="min-h-32 font-mono text-xs"
          />
        </div>
      </div>
    </div>
  )
}
