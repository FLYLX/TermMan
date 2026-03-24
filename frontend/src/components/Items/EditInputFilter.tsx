import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Filter } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemPublic, ItemsService, type ItemUpdate } from "@/client"
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
  input_filter_enabled: z.boolean().optional(),
  input_filter_mode: z.string().optional(),
  input_noise_patterns: z.string().optional(),
  input_event_patterns: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

interface EditInputFilterProps {
  item: ItemPublic
  onSuccess: () => void
}

const EditInputFilter = ({ item, onSuccess }: EditInputFilterProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      input_filter_enabled: item.input_filter_enabled ?? false,
      input_filter_mode: item.input_filter_mode ?? "blacklist",
      input_noise_patterns: item.input_noise_patterns
        ? JSON.stringify(item.input_noise_patterns)
        : "",
      input_event_patterns: item.input_event_patterns
        ? JSON.stringify(item.input_event_patterns)
        : "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ItemUpdate) =>
      ItemsService.updateItem({ id: item.id, requestBody: data }),
    onSuccess: () => {
      showSuccessToast("Input filter updated successfully")
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
      input_filter_enabled: data.input_filter_enabled,
      input_filter_mode: data.input_filter_mode,
      input_noise_patterns: data.input_noise_patterns
        ? JSON.parse(data.input_noise_patterns)
        : null,
      input_event_patterns: data.input_event_patterns
        ? JSON.parse(data.input_event_patterns)
        : null,
    }
    mutation.mutate(formattedData)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Filter />
        Edit Input Filter
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>Edit Input Filter</DialogTitle>
              <DialogDescription>
                Configure input filtering for terminal output to agent.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="input_filter_enabled"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Enable Input Filter</FormLabel>
                    <Select
                      onValueChange={(value) =>
                        field.onChange(value === "true")
                      }
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
                name="input_filter_mode"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Input Filter Mode</FormLabel>
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
                name="input_noise_patterns"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Noise Patterns (JSON array)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder='["^\\s*$", "^\\d+%$"]'
                        type="text"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="input_event_patterns"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Event Patterns (JSON)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder='{"error": ["error:"], "warning": ["warning:"]}'
                        type="text"
                        {...field}
                      />
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

export default EditInputFilter
