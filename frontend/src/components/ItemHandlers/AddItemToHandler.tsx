import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { PlusCircle } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { ItemHandlerAssociationsService, ItemsService } from "@/client"
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
  itemHandlerId: string
}

const AddItemToHandler = ({ itemHandlerId }: AddItemToHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { locale } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const copy =
    locale === "zh"
      ? {
          required: "终端不能为空",
          added: "终端已关联到 TermHandler",
          trigger: "添加终端",
          title: "将终端加入 TermHandler",
          description: "选择一个终端与当前 TermHandler 关联。",
          field: "终端",
          placeholder: "选择一个终端",
          cancel: "取消",
          confirm: "添加",
        }
      : {
          required: "Terminal is required",
          added: "Terminal added to TermHandler successfully",
          trigger: "Add Terminal",
          title: "Add Terminal to TermHandler",
          description: "Select a terminal to associate with this TermHandler.",
          field: "Terminal",
          placeholder: "Select a terminal",
          cancel: "Cancel",
          confirm: "Add",
        }

  const formSchema = z.object({
    itemId: z.string().min(1, { message: copy.required }),
  })

  type FormData = z.infer<typeof formSchema>

  const { data: itemsResult } = useQuery({
    queryFn: () => ItemsService.readItems({ skip: 0, limit: 100 }),
    queryKey: ["items"],
  })

  const items = (itemsResult as any)?.data || []

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      itemId: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      ItemHandlerAssociationsService.addItemToHandler({
        requestBody: { item_handler_id: itemHandlerId, item_id: data.itemId },
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
        <Button
          variant="outline"
          size="sm"
          className="btn-add-compact flex items-center gap-1"
          title={copy.trigger}
        >
          <PlusCircle className="h-4 w-4" />
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
                name="itemId"
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
                        {items?.map((item: any) => (
                          <SelectItem key={item.id} value={item.id}>
                            {item.title} (ID: {item.id.slice(0, 8)}...)
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
