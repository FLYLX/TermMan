import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, ChevronRight, Settings, Terminal } from "lucide-react"
import { useState } from "react"
import { ItemHandlersService, ItemHandlerAssociationsService, SkillsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import useCustomToast from "@/hooks/useCustomToast"

function getItemHandlerQueryOptions(itemHandlerId: string) {
  return {
    queryFn: () => ItemHandlersService.readItemHandler({ id: itemHandlerId }),
    queryKey: ["itemHandler", itemHandlerId],
  }
}

export const Route = createFileRoute("/_layout/item-handlers/$itemHandlerId")({
  component: ItemHandlerDetail,
  head: () => ({
    meta: [
      {
        title: "ItemHandler - TermMan",
      },
    ],
  }),
})

function formatDate(value?: string | null) {
  if (!value) return "N/A"
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">{value || "N/A"}</span>
    </div>
  )
}

function ItemHandlerDetail() {
  const { itemHandlerId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [isSaving, setIsSaving] = useState(false)

  const { data: itemHandler, isLoading } = useQuery({
    ...getItemHandlerQueryOptions(itemHandlerId),
  })

  const { data: items } = useQuery({
    queryFn: () => ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: ["itemHandler-items", itemHandlerId],
  })

  const { data: skillsData } = useQuery({
    queryKey: ["skills"],
    queryFn: () => SkillsService.listSkills({}),
  })

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
            <CardTitle>Enabled Skills ({enabledSkills.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {isEditing ? (
              <ScrollArea className="h-64 border rounded p-2">
                {skills.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-2">
                    No skills available
                  </p>
                ) : (
                  <div className="space-y-2">
                    {skills.map((skill) => (
                      <div
                        key={skill.skill_id}
                        className="flex flex-row items-start space-x-3 space-y-0 p-2 rounded hover:bg-muted"
                      >
                        <Checkbox
                          checked={editForm.enabled_skills.includes(skill.skill_id)}
                          onCheckedChange={() => toggleSkill(skill.skill_id)}
                        />
                        <div className="flex-1">
                          <label className="text-sm font-medium cursor-pointer">
                            {skill.name}
                          </label>
                          <p className="text-xs text-muted-foreground">
                            {skill.skill_id} - {skill.description || "No description"}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </ScrollArea>
            ) : (
              <ScrollArea className="h-64">
                {enabledSkills.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No skills enabled
                  </p>
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

      <Card>
        <CardHeader>
          <CardTitle>Associated Items ({items?.length || 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {!items || items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items associated with this handler
            </p>
          ) : (
            <div className="space-y-2">
              {items.map((item: any) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between p-3 border rounded-lg"
                >
                  <div className="flex items-center gap-3">
                    <Terminal className="size-4 text-muted-foreground" />
                    <div>
                      <Link
                        to="/items/$itemId"
                        params={{ itemId: item.id }}
                        className="font-medium hover:underline"
                      >
                        {item.title}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {item.description || "No description"}
                      </p>
                    </div>
                  </div>
                  <Badge variant={item.status === "running" ? "default" : "secondary"}>
                    {item.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default ItemHandlerDetail
