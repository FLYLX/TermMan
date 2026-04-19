import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link2 } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { ItemHandlerAssociationsService, ItemHandlersService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
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

interface AddItemToHandlerProps {
  itemId: string
}

const AddItemToHandler = ({ itemId }: AddItemToHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { locale } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const copy =
    locale === "zh"
      ? {
          required: "TermHandler 不能为空",
          added: "终端已关联到 TermHandler",
          trigger: "关联 TermHandler",
          title: "关联到 TermHandler",
          description: "选择一个 TermHandler 与当前终端关联。",
          field: "TermHandler",
          placeholder: "选择一个 TermHandler",
          cancel: "取消",
          confirm: "关联",
        }
      : {
          required: "TermHandler is required",
          added: "Terminal added to TermHandler successfully",
          trigger: "Attach TermHandler",
          title: "Attach to TermHandler",
          description: "Select a TermHandler to associate with this terminal.",
          field: "TermHandler",
          placeholder: "Select a TermHandler",
          cancel: "Cancel",
          confirm: "Attach",
        }

  const formSchema = z.object({
    itemHandlerId: z.string().min(1, { message: copy.required }),
  })

  type FormData = z.infer<typeof formSchema>

  const { data: itemHandlers } = useQuery({
    queryFn: () =>
      ItemHandlersService.readItemHandlers({ skip: 0, limit: 100 }),
    queryKey: ["itemHandlers"],
  })

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      itemHandlerId: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      ItemHandlerAssociationsService.addItemToHandler({
        requestBody: { item_handler_id: data.itemHandlerId, item_id: itemId },
      }),
    onSuccess: () => {
      showSuccessToast(copy.added)
      form.reset()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="flex items-center gap-1">
          <Link2 className="h-4 w-4" />
          {copy.trigger}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="itemHandlerId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {copy.field} <span className="text-destructive">*</span>
                    </FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={mutation.isPending}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={copy.placeholder} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {itemHandlers?.map((handler) => (
                          <SelectItem key={handler.id} value={handler.id}>
                            {handler.name} (ID: {handler.id.slice(0, 8)}...)
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  {copy.cancel}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {copy.confirm}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddItemToHandler
