import { useEffect, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, Loader2, Users } from "lucide-react"

import { ItemsService } from "@/client"
import { getStatusLabel } from "@/lib/i18n"
import { useI18n } from "@/components/locale-provider"
import useCustomToast from "@/hooks/useCustomToast"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PasswordInput } from "@/components/ui/password-input"

function formatDate(dateString: string | undefined | null, localeTag: string) {
  if (!dateString) return null
  return new Date(dateString).toLocaleString(localeTag)
}

function KeyValue({ label, value }: { label: string; value?: string | null }) {
  const { t } = useI18n()
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">
        {value || t("common.notAvailable")}
      </span>
    </div>
  )
}

function CopyValue({ label, value }: { label: string; value?: string | null }) {
  const [copiedText, copy] = useCopyToClipboard()
  const { t } = useI18n()
  const displayValue = value || t("common.notAvailable")
  const isCopied = copiedText === displayValue
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm">{displayValue}</span>
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={() => copy(displayValue)}
          >
            {isCopied ? (
              <Check className="size-3 text-green-500" />
            ) : (
              <Copy className="size-3" />
            )}
            <span className="sr-only">{t("common.copyLabel", { label })}</span>
          </Button>
        )}
      </div>
    </div>
  )
}

export function ItemConfigPanel({ itemId }: { itemId: string }) {
  const { t, localeTag, locale } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: item } = useQuery({
    queryKey: ["items", "detail", itemId],
    queryFn: () => ItemsService.readItem({ id: itemId }),
    select: (data) => data as any,
  })

  const [isEditing, setIsEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [form, setForm] = useState({
    title: "",
    description: "",
    socket_host: "",
    socket_port: "",
    api_key: "",
    command: "",
    working_directory: "",
    log_max_size_mb: "100",
  })

  useEffect(() => {
    if (!item) {
      return
    }
    setForm({
      title: item.title ?? "",
      description: item.description ?? "",
      socket_host: item.socket_host ?? "",
      socket_port: item.socket_port?.toString() ?? "",
      api_key: item.api_key ?? "",
      command: item.command ?? "",
      working_directory: item.working_directory ?? "",
      log_max_size_mb: item.log_max_size_mb?.toString() ?? "100",
    })
  }, [item])

  if (!item) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> 正在加载配置…
      </div>
    )
  }

  const handleSave = async () => {
    const title = form.title.trim()
    if (!title) {
      showErrorToast("Title is required")
      return
    }
    const socketPort = form.socket_port.trim() ? Number(form.socket_port) : null
    const logMaxSize = form.log_max_size_mb.trim()
      ? Number(form.log_max_size_mb)
      : null
    setIsSaving(true)
    try {
      const updatedItem = await ItemsService.updateItem({
        id: itemId,
        requestBody: {
          title,
          description: form.description.trim() || null,
          socket_host: form.socket_host.trim() || null,
          socket_port: socketPort,
          api_key: form.api_key.trim() || null,
          command: form.command.trim() || null,
          working_directory: form.working_directory.trim() || null,
          log_max_size_mb: logMaxSize,
        },
      })
      queryClient.setQueryData(["items", "detail", itemId], updatedItem)
      queryClient.invalidateQueries({ queryKey: ["items"] })
      const daemonId =
        updatedItem.socket_host && updatedItem.socket_port && updatedItem.api_key
          ? `${updatedItem.socket_host}:${updatedItem.socket_port}:${updatedItem.api_key}`
          : null
      if (daemonId) {
        await ItemsService.reconnectDaemon({ daemonId }).catch(() => undefined)
      }
      showSuccessToast("Terminal configuration updated")
      setIsEditing(false)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Failed to update terminal",
      )
    } finally {
      setIsSaving(false)
    }
  }

  const set = (key: string, value: string) =>
    setForm((current) => ({ ...current, [key]: value }))

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-xl font-semibold">
            {t("items.detail.keyInformation")}
          </h2>
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setIsEditing(false)}
                  disabled={isSaving}
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleSave()}
                  disabled={isSaving}
                >
                  {isSaving ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : null}
                  {t("common.save")}
                </Button>
              </>
            ) : (
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsEditing(true)}
              >
                Edit
              </Button>
            )}
          </div>
        </div>
        {isEditing ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2">
              <Label>Title</Label>
              <Input value={form.title} onChange={(e) => set("title", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>Description</Label>
              <Input value={form.description} onChange={(e) => set("description", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>{t("items.detail.socketHost")}</Label>
              <Input value={form.socket_host} onChange={(e) => set("socket_host", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>{t("items.detail.socketPort")}</Label>
              <Input type="number" value={form.socket_port} onChange={(e) => set("socket_port", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>Daemon API Key</Label>
              <PasswordInput
                value={form.api_key}
                onChange={(e) => set("api_key", e.target.value)}
                copyable
                copyLabel={t("common.copyLabel", { label: "Daemon API Key" })}
              />
            </div>
            <div className="grid gap-2">
              <Label>{t("items.detail.logMaxSize")}</Label>
              <Input type="number" value={form.log_max_size_mb} onChange={(e) => set("log_max_size_mb", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>{t("items.detail.command")}</Label>
              <Input value={form.command} onChange={(e) => set("command", e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label>{t("items.workingDirectory")}</Label>
              <Input value={form.working_directory} onChange={(e) => set("working_directory", e.target.value)} />
            </div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <CopyValue label={t("common.id")} value={item.id} />
            <KeyValue label={t("common.status")} value={getStatusLabel(locale, item.status)} />
            <KeyValue label={t("common.ownerId")} value={item.owner_id} />
            <KeyValue label={t("items.detail.socketHost")} value={item.socket_host} />
            <KeyValue label={t("items.detail.socketPort")} value={item.socket_port?.toString()} />
            <KeyValue
              label={t("items.detail.socketConnected")}
              value={item.socket_connected ? t("common.yes") : t("common.no")}
            />
            <KeyValue label={t("items.detail.command")} value={item.command} />
            <KeyValue label={t("items.workingDirectory")} value={item.working_directory} />
            <KeyValue label={t("items.detail.logMaxSize")} value={item.log_max_size_mb?.toString()} />
            <KeyValue label={t("items.detail.daemonUrl")} value={item.daemon_url} />
            <KeyValue label={t("common.createdAt")} value={formatDate(item.created_at, localeTag) || undefined} />
            <KeyValue label={t("common.updatedAt")} value={formatDate(item.updated_at, localeTag) || undefined} />
          </div>
        )}
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <h2 className="mb-4 text-xl font-semibold">
          {t("items.detail.connectedUsers")}
        </h2>
        {item.connected_users && Object.keys(item.connected_users).length > 0 ? (
          <div className="space-y-2">
            {Object.entries(item.connected_users).map(([sid, userInfo]: [string, any]) => (
              <div
                key={sid}
                className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <div className="size-2 rounded-full bg-green-500" />
                  <span className="font-mono text-sm">{userInfo.user_uuid}</span>
                </div>
                <span className="text-sm text-muted-foreground">{userInfo.ip}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-8 text-center text-muted-foreground">
            <Users className="mx-auto mb-2 size-8 opacity-50" />
            <p>{t("items.detail.noConnectedUsers")}</p>
          </div>
        )}
      </section>
    </div>
  )
}
