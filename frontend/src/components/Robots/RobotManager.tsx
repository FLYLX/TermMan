import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Bot,
  Cable,
  CirclePlus,
  KeyRound,
  Loader2,
  Search,
  Shield,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"

import {
  createRobot,
  deleteRobot,
  getRobotPlatformsQueryKey,
  getRobotsQueryKey,
  listRobotBindings,
  listRobotPlatforms,
  listRobots,
  type RobotBindingRecord,
  type RobotPlatformField,
  type RobotPlatformRecord,
  type RobotRecord,
} from "./api"

type RobotBindingsMap = Record<string, number>

type RobotFormState = {
  name: string
  platform: string
  credentials: Record<string, string>
}

function normalizePlatformId(platform: string | null | undefined) {
  if (platform === "qq") {
    return "qq_official"
  }
  return platform ?? ""
}

function maskValue(value: string | null | undefined) {
  if (!value) {
    return "-"
  }
  if (value.length <= 8) {
    return value
  }
  return `${value.slice(0, 4)}...${value.slice(-4)}`
}

function buildFormForPlatform(
  platform: RobotPlatformRecord | null,
): RobotFormState {
  return {
    name: "",
    platform: platform?.id ?? "",
    credentials: Object.fromEntries(
      (platform?.fields ?? []).map((field) => [field.key, ""]),
    ),
  }
}

function getRobotCredentials(robot: RobotRecord): Record<string, string> {
  const credentials = robot.config?.credentials
  if (credentials && typeof credentials === "object") {
    return Object.fromEntries(
      Object.entries(credentials)
        .filter(
          ([, value]) => value !== null && value !== undefined && value !== "",
        )
        .map(([key, value]) => [key, String(value)]),
    )
  }

  const normalizedPlatform = normalizePlatformId(robot.platform)
  if (normalizedPlatform === "qq_official") {
    return Object.fromEntries(
      [
        ["app_id", robot.app_id],
        ["app_secret", robot.app_secret],
        ["bot_token", robot.bot_token],
      ].filter(([, value]) => Boolean(value)) as [string, string][],
    )
  }

  return {}
}

function buildCredentialFields(
  platform: RobotPlatformRecord | null,
  credentials: Record<string, string>,
) {
  if (platform?.fields.length) {
    return platform.fields
  }

  return Object.keys(credentials).map(
    (key): RobotPlatformField => ({
      key,
      label: key,
      required: false,
      secret: key.includes("secret") || key.includes("token"),
    }),
  )
}

function RobotStatusBadge({ enabled }: { enabled: boolean }) {
  const { t } = useI18n()

  return enabled ? (
    <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
      {t("robots.enabled")}
    </Badge>
  ) : (
    <Badge variant="secondary">{t("robots.disabled")}</Badge>
  )
}

function CreateRobotDialog({
  platforms,
}: {
  platforms: RobotPlatformRecord[]
}) {
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [open, setOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [form, setForm] = useState<RobotFormState>(() =>
    buildFormForPlatform(platforms[0] ?? null),
  )

  const selectedPlatform =
    platforms.find((platform) => platform.id === form.platform) ??
    platforms[0] ??
    null

  useEffect(() => {
    if (!open || !platforms.length) {
      return
    }

    const hasCurrentPlatform = platforms.some(
      (platform) => platform.id === form.platform,
    )
    if (!hasCurrentPlatform) {
      setForm(buildFormForPlatform(platforms[0] ?? null))
    }
  }, [form.platform, open, platforms])

  const resetForm = () => {
    setForm(buildFormForPlatform(platforms[0] ?? null))
  }

  const handlePlatformChange = (platformId: string) => {
    const platform = platforms.find((entry) => entry.id === platformId) ?? null
    setForm((current) => ({
      ...current,
      platform: platformId,
      credentials: Object.fromEntries(
        (platform?.fields ?? []).map((field) => [
          field.key,
          current.credentials[field.key] ?? "",
        ]),
      ),
    }))
  }

  const handleSubmit = async () => {
    if (!selectedPlatform) {
      showErrorToast(t("robots.noPlatformsDescription"))
      return
    }
    if (!form.name.trim()) {
      showErrorToast(t("robots.nameRequired"))
      return
    }

    const missingField = selectedPlatform.fields.find(
      (field) => field.required && !form.credentials[field.key]?.trim(),
    )
    if (missingField) {
      showErrorToast(t("robots.credentialsRequired"))
      return
    }

    const credentials = Object.fromEntries(
      selectedPlatform.fields
        .map(
          (field) =>
            [field.key, form.credentials[field.key]?.trim() ?? ""] as const,
        )
        .filter(([, value]) => value !== ""),
    )

    setIsSubmitting(true)
    try {
      await createRobot({
        name: form.name.trim(),
        platform: selectedPlatform.id,
        protocol: selectedPlatform.id,
        provider: selectedPlatform.provider,
        is_enabled: true,
        use_websocket: selectedPlatform.id === "qq_official",
        config: {
          credentials,
          options:
            selectedPlatform.id === "qq_official"
              ? { use_websocket: true }
              : {},
        },
      })
      await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
      await queryClient.invalidateQueries({
        queryKey: getRobotPlatformsQueryKey(),
      })
      showSuccessToast(t("robots.createSuccess"))
      setOpen(false)
      resetForm()
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : t("robots.createFailed"),
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          resetForm()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          className="h-9 rounded-xl px-3.5"
          disabled={platforms.length === 0}
        >
          <CirclePlus className="mr-2 size-4" />
          {t("robots.add")}
        </Button>
      </DialogTrigger>
      <DialogContent className="rounded-2xl">
        <DialogHeader>
          <DialogTitle>{t("robots.addTitle")}</DialogTitle>
          <DialogDescription>{t("robots.addDescription")}</DialogDescription>
        </DialogHeader>

        {platforms.length === 0 ? (
          <div className="rounded-2xl border border-dashed px-4 py-6 text-sm text-muted-foreground">
            <div className="font-medium text-foreground">
              {t("robots.noPlatforms")}
            </div>
            <div className="mt-1">{t("robots.noPlatformsDescription")}</div>
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="robot-name">{t("common.name")}</Label>
              <Input
                id="robot-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder={t("robots.namePlaceholder")}
              />
            </div>

            <div className="grid gap-2">
              <Label>{t("robots.platform")}</Label>
              <Select
                value={form.platform}
                onValueChange={handlePlatformChange}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("robots.platformPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {platforms.map((platform) => (
                    <SelectItem key={platform.id} value={platform.id}>
                      {platform.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedPlatform ? (
                <p className="text-xs text-muted-foreground">
                  {selectedPlatform.description}
                </p>
              ) : null}
            </div>

            <div className="grid gap-3">
              <div className="text-sm font-medium">
                {t("robots.credentials")}
              </div>
              {(selectedPlatform?.fields ?? []).map((field) => (
                <div key={field.key} className="grid gap-2">
                  <Label htmlFor={`robot-field-${field.key}`}>
                    {field.label}
                    {field.required ? " *" : ""}
                  </Label>
                  {field.key === "private_key" ? (
                    <Textarea
                      id={`robot-field-${field.key}`}
                      value={form.credentials[field.key] ?? ""}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          credentials: {
                            ...current.credentials,
                            [field.key]: event.target.value,
                          },
                        }))
                      }
                      placeholder={field.label}
                      className="min-h-28"
                    />
                  ) : (
                    <Input
                      id={`robot-field-${field.key}`}
                      type={field.secret ? "password" : "text"}
                      value={form.credentials[field.key] ?? ""}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          credentials: {
                            ...current.credentials,
                            [field.key]: event.target.value,
                          },
                        }))
                      }
                      placeholder={field.label}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isSubmitting}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || platforms.length === 0}
          >
            {isSubmitting ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : null}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RobotCard({
  robot,
  bindingCount,
  platformMap,
  onDelete,
  deletingRobotId,
}: {
  robot: RobotRecord
  bindingCount: number
  platformMap: Map<string, RobotPlatformRecord>
  onDelete: (robot: RobotRecord) => void
  deletingRobotId: string | null
}) {
  const { locale, t } = useI18n()
  const platform = platformMap.get(normalizePlatformId(robot.platform)) ?? null
  const credentials = getRobotCredentials(robot)
  const credentialFields = buildCredentialFields(platform, credentials).slice(
    0,
    3,
  )
  const manageLabel = locale === "zh" ? "管理绑定" : "Manage"

  return (
    <div className="rounded-[22px] border bg-card p-4 shadow-sm transition-transform hover:-translate-y-0.5 hover:border-primary/25">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
            <Bot className="size-4.5" />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="truncate text-sm font-semibold">{robot.name}</div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span>{platform?.label ?? robot.platform}</span>
              <span>/</span>
              <span>{robot.provider}</span>
            </div>
            {platform?.description ? (
              <div className="line-clamp-1 text-[12px] text-muted-foreground">
                {platform.description}
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <RobotStatusBadge enabled={robot.is_enabled} />
          <Button
            asChild
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-3"
          >
            <Link to="/robots/$robotId" params={{ robotId: robot.id }}>
              {manageLabel}
            </Link>
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="h-8 rounded-lg px-2.5"
            onClick={() => onDelete(robot)}
            disabled={deletingRobotId === robot.id}
          >
            {deletingRobotId === robot.id ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Trash2 className="size-3.5" />
            )}
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border bg-muted/20 px-3 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em]">
            <Cable className="size-3.5" />
            {t("robots.platform")}
          </div>
          <div className="truncate text-foreground">
            {platform?.label ?? robot.platform}
          </div>
        </div>

        {credentialFields.map((field, index) => (
          <div
            key={field.key}
            className="rounded-xl border bg-muted/20 px-3 py-2"
          >
            <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em]">
              {index % 2 === 0 ? (
                <Shield className="size-3.5" />
              ) : (
                <KeyRound className="size-3.5" />
              )}
              {field.label}
            </div>
            <div className="truncate text-foreground">
              {field.secret
                ? maskValue(credentials[field.key])
                : credentials[field.key] || t("common.notSet")}
            </div>
          </div>
        ))}

        <div className="rounded-xl border bg-muted/20 px-3 py-2">
          <div className="mb-1 text-[11px] uppercase tracking-[0.18em]">
            {t("robots.bindings")}
          </div>
          <div className="text-foreground">
            {bindingCount} {t("nav.items")}
          </div>
        </div>
      </div>
    </div>
  )
}

export function RobotManager() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [searchQuery, setSearchQuery] = useState("")
  const [deletingRobotId, setDeletingRobotId] = useState<string | null>(null)

  const { data: robotsData, isLoading } = useQuery({
    queryKey: getRobotsQueryKey(),
    queryFn: () => listRobots(),
  })

  const { data: platforms = [] } = useQuery({
    queryKey: getRobotPlatformsQueryKey(),
    queryFn: () => listRobotPlatforms(),
  })

  const platformMap = useMemo(
    () => new Map(platforms.map((platform) => [platform.id, platform])),
    [platforms],
  )

  const robots = robotsData?.data ?? []

  const { data: bindingCounts = {} } = useQuery<RobotBindingsMap>({
    queryKey: ["robot-bindings", robots.map((robot) => robot.id).join(",")],
    enabled: robots.length > 0,
    queryFn: async () => {
      const entries = await Promise.all(
        robots.map(async (robot) => {
          try {
            const bindings: RobotBindingRecord[] = await listRobotBindings(
              robot.id,
            )
            return [robot.id, bindings.length] as const
          } catch {
            return [robot.id, 0] as const
          }
        }),
      )
      return Object.fromEntries(entries)
    },
  })

  const filteredRobots = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    if (!normalizedQuery) {
      return robots
    }

    return robots.filter((robot) => {
      const platform = platformMap.get(normalizePlatformId(robot.platform))
      const credentialValues = Object.values(getRobotCredentials(robot))
      return [
        robot.name,
        robot.platform,
        robot.protocol,
        robot.provider,
        platform?.label,
        ...credentialValues,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery))
    })
  }, [platformMap, robots, searchQuery])

  const totalBindings = Object.values(bindingCounts).reduce(
    (sum, count) => sum + count,
    0,
  )

  const handleDelete = async (robot: RobotRecord) => {
    if (!window.confirm(t("robots.deleteConfirm", { name: robot.name }))) {
      return
    }

    setDeletingRobotId(robot.id)
    try {
      await deleteRobot(robot.id)
      await queryClient.invalidateQueries({ queryKey: getRobotsQueryKey() })
      await queryClient.invalidateQueries({ queryKey: ["robot-bindings"] })
      showSuccessToast(t("robots.deleteSuccess"))
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : t("robots.deleteFailed"),
      )
    } finally {
      setDeletingRobotId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-3xl border bg-card px-4 py-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {t("robots.pageTitle")}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("robots.pageDescription")}
            </p>
          </div>
          <CreateRobotDialog platforms={platforms} />
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            {t("robots.pageTitle")}
          </div>
          <div className="mt-2 text-2xl font-semibold">{robots.length}</div>
        </div>
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            {t("robots.bindings")}
          </div>
          <div className="mt-2 text-2xl font-semibold">{totalBindings}</div>
        </div>
        <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            {t("robots.platform")}
          </div>
          <div className="mt-2 text-2xl font-semibold">{platforms.length}</div>
        </div>
      </section>

      <section className="rounded-3xl border bg-card p-4 shadow-sm">
        <div className="relative max-w-lg">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("robots.search")}
            className="h-9 rounded-xl bg-background pl-10"
          />
        </div>

        <div className="mt-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {t("common.loading")}
            </div>
          ) : filteredRobots.length === 0 ? (
            <div className="rounded-2xl border border-dashed bg-muted/10 px-6 py-10 text-center">
              <div className="mx-auto flex size-12 items-center justify-center rounded-full border bg-muted/20 text-muted-foreground">
                <Bot className="size-5" />
              </div>
              <div className="mt-4 text-sm font-medium">
                {robots.length === 0
                  ? t("robots.emptyTitle")
                  : t("table.noResults")}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {robots.length === 0
                  ? t("robots.emptyDescription")
                  : t("robots.searchEmpty")}
              </div>
            </div>
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {filteredRobots.map((robot) => (
                <RobotCard
                  key={robot.id}
                  robot={robot}
                  bindingCount={bindingCounts[robot.id] ?? 0}
                  platformMap={platformMap}
                  onDelete={handleDelete}
                  deletingRobotId={deletingRobotId}
                />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
