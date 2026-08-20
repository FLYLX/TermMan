import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Plus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemHandlerCreate, ItemHandlersService } from "@/client"
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
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  name: z.string().min(1, { message: "Name is required" }),
  model: z.string().optional(),
  api_key: z.string().optional(),
  api_url: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

type AddItemHandlerProps = {
  triggerClassName?: string
  triggerLabel?: string
  triggerVariant?: "default" | "outline" | "secondary"
}

const AddItemHandler = ({
  triggerClassName,
  triggerLabel,
  triggerVariant = "default",
}: AddItemHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(
      formSchema.extend({
        name: z.string().min(1, { message: t("itemHandlers.nameRequired") }),
      }),
    ),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: "",
      model: "",
      api_key: "",
      api_url: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ItemHandlerCreate) =>
      ItemHandlersService.createItemHandler({ requestBody: data }),
    onSuccess: (created: any) => {
      showSuccessToast(t("itemHandlers.handlerCreated"))
      form.reset()
      setIsOpen(false)
      // 创建完直接切到该调度器，激活拉线圆圈
      if (created?.id) {
        void navigate({
          to: "/item-handlers/$itemHandlerId",
          params: { itemHandlerId: String(created.id) },
        })
      }
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
      <DialogTrigger asChild>
        <Button
          className={triggerClassName}
          variant={triggerVariant}
          title={triggerLabel || t("itemHandlers.add")}
        >
          <Plus className={triggerLabel ? "mr-2" : ""} />
          {triggerLabel || null}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("itemHandlers.addTitle")}</DialogTitle>
          <DialogDescription>
            {t("itemHandlers.addDescription")}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t("common.name")}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t("common.name")}
                        type="text"
                        {...field}
                        required
                      />
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
                    <FormLabel>{t("common.model")}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t("common.model")}
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
                name="api_key"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("common.apiKey")}</FormLabel>
                    <FormControl>
                      <PasswordInput
                        placeholder={t("common.apiKey")}
                        autoComplete="new-password"
                        {...field}
                      />
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
                    <FormLabel>{t("common.apiUrl")}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t("common.apiUrl")}
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
                  {t("common.cancel")}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {t("common.save")}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddItemHandler
