import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Shield } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemPublic, type ItemUpdate, ItemsService } from "@/client"
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  output_filter_enabled: z.boolean().optional(),
  output_filter_mode: z.string().optional(),
  output_command_list: z.string().optional(),
  output_sensitive_patterns: z.string().optional(),
  output_rate_limit: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

interface EditOutputFilterProps {
  item: ItemPublic
  onSuccess: () => void
}

const EditOutputFilter = ({ item, onSuccess }: EditOutputFilterProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      output_filter_enabled: item.output_filter_enabled ?? false,
      output_filter_mode: item.output_filter_mode ?? "blacklist",
      output_command_list: item.output_command_list ? JSON.stringify(item.output_command_list) : "",
      output_sensitive_patterns: item.output_sensitive_patterns ? JSON.stringify(item.output_sensitive_patterns) : "",
      output_rate_limit: item.output_rate_limit?.toString() ?? "10",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ItemUpdate) =>
      ItemsService.updateItem({ id: item.id, requestBody: data }),
    onSuccess: () => {
      showSuccessToast("Output filter updated successfully")
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
      output_filter_enabled: data.output_filter_enabled,
      output_filter_mode: data.output_filter_mode,
      output_command_list: data.output_command_list ? JSON.parse(data.output_command_list) : null,
      output_sensitive_patterns: data.output_sensitive_patterns ? JSON.parse(data.output_sensitive_patterns) : null,
      output_rate_limit: data.output_rate_limit ? parseInt(data.output_rate_limit, 10) : null,
    }
    mutation.mutate(formattedData)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Shield />
        Edit Output Filter
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>Edit Output Filter</DialogTitle>
              <DialogDescription>
                Configure output filtering for agent commands to terminal.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="output_filter_enabled"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Enable Output Filter</FormLabel>
                    <Select
                      onValueChange={(value) => field.onChange(value === "true")}
                      value={field.value?.toString()}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select option" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="true">Enabled</SelectItem>
                        <SelectItem value="false">Disabled</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="output_filter_mode"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Output Filter Mode</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select mode" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="blacklist">Blacklist</SelectItem>
                        <SelectItem value="whitelist">Whitelist</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="output_command_list"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Command Filter List (JSON array)</FormLabel>
                    <FormControl>
                      <Input placeholder='["rm -rf", "chmod 777", "shutdown"]' type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="output_sensitive_patterns"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Sensitive Patterns (JSON array)</FormLabel>
                    <FormControl>
                      <Input placeholder='["password", "api_key", "secret"]' type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="output_rate_limit"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Rate Limit (commands/min)</FormLabel>
                    <FormControl>
                      <Input placeholder="10" type="number" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

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

export default EditOutputFilter
