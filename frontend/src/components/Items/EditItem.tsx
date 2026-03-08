import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemPublic, type ItemUpdate, ItemsService } from "@/client"
import ItemHandlersList from "./ItemHandlersList"
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
import { Separator } from "@/components/ui/separator"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  title: z.string().min(1, { message: "Title is required" }),
  description: z.string().optional(),
  // daemon settings
  socket_host: z.string().optional(),
  socket_port: z.string().optional(),
  // Command settings
  command: z.string().optional(),
  executable_path: z.string().optional(),
  working_directory: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

interface EditItemProps {
  item: ItemPublic
  onSuccess: () => void
}

const EditItem = ({ item, onSuccess }: EditItemProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: item.title,
      description: item.description ?? undefined,
      // daemon settings
      socket_host: item.socket_host ?? "",
      socket_port: item.socket_port?.toString() ?? "",
      // Command settings
      command: item.command ?? "",
      executable_path: item.executable_path ?? "",
      working_directory: item.working_directory ?? "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ItemUpdate) =>
      ItemsService.updateItem({ id: item.id, requestBody: data }),
    onSuccess: () => {
      showSuccessToast("Item updated successfully")
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const onSubmit = (data: FormData) => {
    const formattedData: ItemUpdate = {
      ...data,
      socket_port: data.socket_port ? parseInt(data.socket_port, 10) : null,
    }
    mutation.mutate(formattedData)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Pencil />
        Edit Item
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>Edit Item</DialogTitle>
              <DialogDescription>
                Update the item details below.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Title <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input placeholder="Title" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Input placeholder="Description" type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* daemon Settings */}
              <div className="grid gap-2">
                <h4 className="font-semibold text-sm text-gray-700">daemon Settings</h4>
                <FormField
                  control={form.control}
                  name="socket_host"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>IP</FormLabel>
                      <FormControl>
                        <Input placeholder="IP address" type="text" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="socket_port"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Port</FormLabel>
                      <FormControl>
                        <Input placeholder="Port number" type="number" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="command"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Start Command</FormLabel>
                      <FormControl>
                        <Input placeholder="Command to start the daemon" type="text" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="executable_path"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Executable Path</FormLabel>
                      <FormControl>
                        <Input placeholder="Path to executable" type="text" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="working_directory"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Working Directory</FormLabel>
                      <FormControl>
                        <Input placeholder="Working directory path" type="text" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>
            <Separator className="my-4" />
            <ItemHandlersList itemId={item.id} />

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

export default EditItem
