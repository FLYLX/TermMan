import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Sparkles } from "lucide-react"
import { useEffect, useState } from "react"

import { ItemHandlersService, SkillsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { apiRequest } from "@/lib/api-request"

type GeneratedSkillResponse = {
  skill_id: string
  name: string
  description: string
  category: string
  trigger: Record<string, unknown>
  action: Record<string, unknown>
  safety: Record<string, unknown>
  content: string
  skill_markdown: string
  item_handler_id: string
  model: string
}

interface GenerateSkillDialogProps {
  onCreated?: (skillId: string) => void
}

export default function GenerateSkillDialog({
  onCreated,
}: GenerateSkillDialogProps) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [open, setOpen] = useState(false)
  const [itemHandlerId, setItemHandlerId] = useState("")
  const [skillId, setSkillId] = useState("")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("general")
  const [instruction, setInstruction] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [generated, setGenerated] = useState<GeneratedSkillResponse | null>(
    null,
  )

  const { data: handlersData } = useQuery({
    queryKey: ["itemHandlers", "for-skill-generator"],
    queryFn: () => ItemHandlersService.readItemHandlers(),
    enabled: open,
  })

  const handlers = handlersData || []

  useEffect(() => {
    if (!open || itemHandlerId || handlers.length === 0) {
      return
    }
    const firstHandler = handlers[0]
    if (firstHandler?.id) {
      setItemHandlerId(firstHandler.id)
    }
  }, [handlers, itemHandlerId, open])

  const resetState = () => {
    setItemHandlerId("")
    setSkillId("")
    setName("")
    setDescription("")
    setCategory("general")
    setInstruction("")
    setGenerated(null)
    setIsGenerating(false)
    setIsCreating(false)
  }

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (!nextOpen) {
      resetState()
    }
  }

  const handleGenerate = async () => {
    if (
      !itemHandlerId ||
      !skillId.trim() ||
      !name.trim() ||
      !instruction.trim()
    ) {
      showErrorToast("Handler, skill id, name, and instruction are required")
      return
    }

    setIsGenerating(true)
    try {
      const result = await apiRequest<GeneratedSkillResponse>(
        "/api/v1/skills/generate",
        {
          method: "POST",
          body: JSON.stringify({
            item_handler_id: itemHandlerId,
            skill_id: skillId.trim(),
            name: name.trim(),
            description: description.trim(),
            category: category.trim() || "general",
            instruction: instruction.trim(),
          }),
        },
      )
      setGenerated(result)
      showSuccessToast("Generated SKILL.md preview")
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Failed to generate skill",
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const handleCreate = async () => {
    if (!generated) {
      return
    }

    setIsCreating(true)
    try {
      await SkillsService.createSkill({
        requestBody: {
          skill_id: generated.skill_id,
          name: generated.name,
          description: generated.description,
          category: generated.category,
        },
      })
      await SkillsService.updateSkillFile({
        skillId: generated.skill_id,
        filePath: "SKILL.md",
        requestBody: {
          content: generated.skill_markdown,
        },
      })
      await queryClient.invalidateQueries({ queryKey: ["skills"] })
      await queryClient.invalidateQueries({
        queryKey: ["skill", generated.skill_id],
      })
      await queryClient.invalidateQueries({
        queryKey: ["skill-files", generated.skill_id],
      })
      onCreated?.(generated.skill_id)
      showSuccessToast("Skill created from generated SKILL.md")
      setOpen(false)
      resetState()
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Failed to create skill",
      )
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Sparkles className="mr-2 h-4 w-4" />
          Generate
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Generate Skill With LLM</DialogTitle>
          <DialogDescription>
            Choose a TermHandler as the model source, describe the behavior,
            then create a new skill from the generated SKILL.md preview.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[420px_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>TermHandler</Label>
              <Select value={itemHandlerId} onValueChange={setItemHandlerId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a TermHandler" />
                </SelectTrigger>
                <SelectContent>
                  {handlers.map((handler) => (
                    <SelectItem key={handler.id} value={handler.id}>
                      {handler.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Skill ID</Label>
                <Input
                  value={skillId}
                  onChange={(event) => setSkillId(event.target.value)}
                  placeholder="log_guard"
                />
              </div>
              <div className="space-y-2">
                <Label>Category</Label>
                <Input
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  placeholder="general"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Log Guard"
              />
            </div>

            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Short summary for the skill list"
              />
            </div>

            <div className="space-y-2">
              <Label>Instruction</Label>
              <Textarea
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="Describe what this skill should do, when it should trigger, and any safety constraints."
                className="min-h-40"
              />
            </div>
          </div>

          <div className="flex min-h-0 flex-col rounded-lg border bg-muted/20">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="text-sm font-medium">Generated SKILL.md</div>
                <div className="text-xs text-muted-foreground">
                  Review the preview before creating the skill.
                </div>
              </div>
              <div className="flex items-center gap-2">
                {generated?.model && (
                  <Badge variant="secondary" className="text-[10px]">
                    {generated.model}
                  </Badge>
                )}
                <Button
                  type="button"
                  size="sm"
                  onClick={handleGenerate}
                  disabled={isGenerating || handlers.length === 0}
                >
                  {isGenerating ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="mr-2 h-4 w-4" />
                  )}
                  Generate
                </Button>
              </div>
            </div>

            <div className="flex-1 p-3">
              <Textarea
                readOnly
                value={generated?.skill_markdown || ""}
                placeholder="The generated SKILL.md preview will appear here."
                className="h-[24rem] font-mono text-xs"
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!generated || isCreating}>
            {isCreating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            Create Skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
