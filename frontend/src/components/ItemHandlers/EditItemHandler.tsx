import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemHandlerPublic, ItemHandlersService, SkillsService, McpService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { Separator } from "@/components/ui/separator"
import { Checkbox } from "@/components/ui/checkbox"
import { ScrollArea } from "@/components/ui/scroll-area"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import ItemHandlerItemsList from "./ItemHandlerItemsList"

const formSchema = z.object({
  name: z.string().min(1, { message: "Name is required" }),
  model: z.string().optional(),
  api_key: z.string().optional(),
  api_url: z.string().optional(),
  enabled_skills: z.array(z.string()).optional(),
  enabled_mcp_servers: z.array(z.string()).optional(),
})

type FormData = z.infer<typeof formSchema>

interface EditItemHandlerProps {
  itemHandler: ItemHandlerPublic
  onSuccess: () => void
}

const EditItemHandler = ({ itemHandler, onSuccess }: EditItemHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: skillsData } = useQuery({
    queryKey: ["skills"],
    queryFn: () => SkillsService.listSkills({}),
    enabled: isOpen,
  })

  const { data: mcpData } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: () => McpService.listMcpServers(),
    enabled: isOpen,
  })

  const skills = skillsData?.data || []
  const mcpServers = mcpData?.data || []

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: itemHandler.name,
      model: itemHandler.model ?? "",
      api_key: itemHandler.api_key ?? "",
      api_url: itemHandler.api_url ?? "",
      enabled_skills: itemHandler.enabled_skills ?? [],
      enabled_mcp_servers: (itemHandler as any).enabled_mcp_servers ?? [],
    },
  })

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      ItemHandlersService.updateItemHandler({
        id: itemHandler.id,
        requestBody: data,
      }),
    onSuccess: () => {
      showSuccessToast("ItemHandler updated successfully")
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Pencil />
        Edit ItemHandler
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>Edit ItemHandler</DialogTitle>
              <DialogDescription>
                Update the item handler details below.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Name <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input placeholder="Name" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="model"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Model</FormLabel>
                    <FormControl>
                      <Input placeholder="Model" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="api_key"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>API Key</FormLabel>
                    <FormControl>
                      <Input placeholder="API Key" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="api_url"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>API URL</FormLabel>
                    <FormControl>
                      <Input placeholder="API URL" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="enabled_skills"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Enabled Skills</FormLabel>
                    <FormDescription>
                      Select skills to enable for this handler
                    </FormDescription>
                    <ScrollArea className="h-32 border rounded p-2">
                      {skills.length === 0 ? (
                        <p className="text-sm text-muted-foreground p-2">
                          No skills available
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {skills.map((skill) => (
                            <FormItem
                              key={skill.skill_id}
                              className="flex flex-row items-start space-x-3 space-y-0"
                            >
                              <FormControl>
                                <Checkbox
                                  checked={field.value?.includes(skill.skill_id)}
                                  onCheckedChange={(checked) => {
                                    const currentValue = field.value || []
                                    if (checked) {
                                      field.onChange([...currentValue, skill.skill_id])
                                    } else {
                                      field.onChange(
                                        currentValue.filter((v) => v !== skill.skill_id)
                                      )
                                    }
                                  }}
                                />
                              </FormControl>
                              <FormLabel className="text-sm font-normal cursor-pointer">
                                {skill.name}
                                <span className="text-muted-foreground ml-1">
                                  ({skill.skill_id})
                                </span>
                              </FormLabel>
                            </FormItem>
                          ))}
                        </div>
                      )}
                    </ScrollArea>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="enabled_mcp_servers"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>MCP Servers</FormLabel>
                    <FormDescription>
                      Select MCP servers to enable for this handler
                    </FormDescription>
                    <ScrollArea className="h-32 border rounded p-2">
                      {mcpServers.length === 0 ? (
                        <p className="text-sm text-muted-foreground p-2">
                          No MCP servers available
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {mcpServers.map((server: any) => (
                            <FormItem
                              key={server.name}
                              className="flex flex-row items-start space-x-3 space-y-0"
                            >
                              <FormControl>
                                <Checkbox
                                  checked={field.value?.includes(server.name)}
                                  onCheckedChange={(checked) => {
                                    const currentValue = field.value || []
                                    if (checked) {
                                      field.onChange([...currentValue, server.name])
                                    } else {
                                      field.onChange(
                                        currentValue.filter((v: string) => v !== server.name)
                                      )
                                    }
                                  }}
                                />
                              </FormControl>
                              <FormLabel className="text-sm font-normal cursor-pointer">
                                {server.name}
                                {server.description && (
                                  <span className="text-muted-foreground ml-1">
                                    - {server.description}
                                  </span>
                                )}
                              </FormLabel>
                            </FormItem>
                          ))}
                        </div>
                      )}
                    </ScrollArea>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <Separator className="my-4" />
            <ItemHandlerItemsList itemHandlerId={itemHandler.id} />
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                Save
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default EditItemHandler
