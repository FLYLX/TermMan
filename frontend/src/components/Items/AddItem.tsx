import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Terminal } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ItemCreate, ItemsService } from "@/client"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import {
  CUSTOM_DAEMON_KEY,
  groupItemsByDaemon,
  type TerminalItem,
} from "./terminal-utils"

const formSchema = z
  .object({
    title: z.string().trim().min(1, "Title is required").max(255),
    daemon_key: z.string().min(1),
    command: z.string().min(1),
    working_directory: z.string().optional(),
    socket_host: z.string().optional(),
    socket_port: z.string().optional(),
    api_key: z.string().optional(),
  })
  .superRefine((data, ctx) => {
    if (data.daemon_key !== CUSTOM_DAEMON_KEY) {
      return
    }

    if (!data.socket_host?.trim()) {
      ctx.addIssue({
        code: "custom",
        message: "Host is required",
        path: ["socket_host"],
      })
    }

    if (!data.socket_port?.trim()) {
      ctx.addIssue({
        code: "custom",
        message: "Port is required",
        path: ["socket_port"],
      })
    } else {
      const port = Number.parseInt(data.socket_port, 10)
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        ctx.addIssue({
          code: "custom",
          message: "Port must be between 1 and 65535",
          path: ["socket_port"],
        })
      }
    }

    if (!data.api_key?.trim()) {
      ctx.addIssue({
        code: "custom",
        message: "API key is required",
        path: ["api_key"],
      })
    }
  })

type FormData = z.infer<typeof formSchema>

type AddItemProps = {
  items: TerminalItem[]
  initialDaemonKey?: string
  triggerClassName?: string
  triggerLabel?: string
  triggerVariant?: "default" | "outline" | "secondary"
}

const AddItem = ({
  items,
  initialDaemonKey,
  triggerClassName,
  triggerLabel,
  triggerVariant = "default",
}: AddItemProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { locale, t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const copy =
    locale === "zh"
      ? {
          trigger: triggerLabel || "新建终端",
          title: "新建终端",
          description: "选择一个 Daemon，然后只填写指令和工作目录。",
          terminalTitle: "标题",
          terminalTitlePlaceholder: "例如：main",
          daemonField: "Daemon",
          daemonPlaceholder: "选择一个可用的 Daemon",
          customDaemon: "手动填写 Daemon",
          terminalSection: "终端配置",
          terminalCommand: "指令",
          terminalCommandPlaceholder: "例如：python app.py",
          workingDirectory: "工作目录",
          workingDirectoryPlaceholder: "例如：/workspace/project",
          manualHost: "Daemon IP",
          manualPort: "Daemon 端口",
          manualApiKey: "Daemon API Key",
          create: "创建终端",
          noDaemons: "当前还没有可复用的 Daemon，先手动填写一组连接信息即可。",
        }
      : {
          trigger: triggerLabel || "New Terminal",
          title: "New Terminal",
          description:
            "Select a daemon first, then only fill in the command and working directory.",
          terminalTitle: "Title",
          terminalTitlePlaceholder: "Example: main",
          daemonField: "Daemon",
          daemonPlaceholder: "Select an available daemon",
          customDaemon: "Enter daemon manually",
          terminalSection: "Terminal config",
          terminalCommand: "Command",
          terminalCommandPlaceholder: "Example: python app.py",
          workingDirectory: "Working directory",
          workingDirectoryPlaceholder: "Example: /workspace/project",
          manualHost: "Daemon IP",
          manualPort: "Daemon port",
          manualApiKey: "Daemon API key",
          create: "Create Terminal",
          noDaemons:
            "No reusable daemon is configured yet. Enter one manually to create the first terminal.",
        }

  const daemonGroups = useMemo(
    () => groupItemsByDaemon(items).filter((group) => group.isConfigured),
    [items],
  )

  const defaultDaemonKey = useMemo(() => {
    if (
      initialDaemonKey &&
      daemonGroups.some((group) => group.key === initialDaemonKey)
    ) {
      return initialDaemonKey
    }

    return daemonGroups[0]?.key ?? CUSTOM_DAEMON_KEY
  }, [daemonGroups, initialDaemonKey])

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: "",
      daemon_key: defaultDaemonKey,
      command: "",
      working_directory: "",
      socket_host: "",
      socket_port: "",
      api_key: "",
    },
  })

  useEffect(() => {
    if (!isOpen) {
      return
    }

    form.reset({
      title: "",
      daemon_key: defaultDaemonKey,
      command: "",
      working_directory: "",
      socket_host: "",
      socket_port: "",
      api_key: "",
    })
  }, [defaultDaemonKey, form, isOpen])

  const selectedDaemonKey = form.watch("daemon_key")
  const selectedDaemon = daemonGroups.find(
    (group) => group.key === selectedDaemonKey,
  )
  const isCustomDaemon = selectedDaemonKey === CUSTOM_DAEMON_KEY

  const mutation = useMutation({
    mutationFn: (data: ItemCreate) =>
      ItemsService.createItem({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast(t("items.itemCreated"))
      form.reset({
        title: "",
        daemon_key: defaultDaemonKey,
        command: "",
        working_directory: "",
        socket_host: "",
        socket_port: "",
        api_key: "",
      })
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const onSubmit = (data: FormData) => {
    const daemon = selectedDaemon
      ? {
          socket_host: selectedDaemon.host?.trim() || undefined,
          socket_port: selectedDaemon.port ?? undefined,
          api_key: selectedDaemon.apiKey?.trim() || undefined,
        }
      : {
          socket_host: data.socket_host?.trim() || undefined,
          socket_port: data.socket_port
            ? Number.parseInt(data.socket_port, 10)
            : undefined,
          api_key: data.api_key?.trim() || undefined,
        }

    const formattedData: ItemCreate = {
      title: data.title.trim(),
      command: data.command.trim(),
      working_directory: data.working_directory?.trim() || undefined,
      socket_host: daemon.socket_host,
      socket_port: daemon.socket_port,
      api_key: daemon.api_key,
    }

    mutation.mutate(formattedData)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button
          className={triggerClassName}
          variant={triggerVariant}
          title={triggerLabel || copy.trigger}
        >
          <Plus className={triggerLabel ? "mr-2 size-4" : "size-4"} />
          {triggerLabel || null}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
            <div className="grid gap-4">
              <FormField
                control={form.control}
                name="daemon_key"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{copy.daemonField}</FormLabel>
                    <Select
                      defaultValue={field.value}
                      onValueChange={field.onChange}
                      value={field.value}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder={copy.daemonPlaceholder} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {daemonGroups.map((group) => (
                          <SelectItem key={group.key} value={group.key}>
                            {group.label}
                          </SelectItem>
                        ))}
                        <SelectItem value={CUSTOM_DAEMON_KEY}>
                          {copy.customDaemon}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {daemonGroups.length === 0 && (
                <div className="rounded-xl border border-dashed bg-muted/25 px-4 py-3 text-sm text-muted-foreground">
                  {copy.noDaemons}
                </div>
              )}

              {isCustomDaemon && (
                <div className="grid gap-4 rounded-2xl border bg-muted/20 p-4 sm:grid-cols-3">
                  <FormField
                    control={form.control}
                    name="socket_host"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{copy.manualHost}</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="127.0.0.1"
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
                    name="socket_port"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{copy.manualPort}</FormLabel>
                        <FormControl>
                          <Input placeholder="8000" type="number" {...field} />
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
                        <FormLabel>{copy.manualApiKey}</FormLabel>
                        <FormControl>
                          <PasswordInput
                            placeholder="daemon-secret"
                            copyable
                            copyLabel={t("common.copyLabel", {
                              label: copy.manualApiKey,
                            })}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}

              <div className="grid gap-4 rounded-2xl border bg-card/70 p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Terminal className="size-4 text-violet-500" />
                  {copy.terminalSection}
                </div>

                <FormField
                  control={form.control}
                  name="title"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{copy.terminalTitle}</FormLabel>
                      <FormControl>
                        <Input
                          placeholder={copy.terminalTitlePlaceholder}
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
                  name="command"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{copy.terminalCommand}</FormLabel>
                      <FormControl>
                        <Input
                          placeholder={copy.terminalCommandPlaceholder}
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
                  name="working_directory"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{copy.workingDirectory}</FormLabel>
                      <FormControl>
                        <Input
                          placeholder={copy.workingDirectoryPlaceholder}
                          type="text"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  {t("common.cancel")}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {copy.create}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddItem
