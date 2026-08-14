import { useEffect, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Settings } from "lucide-react"

import { ApiError, type ItemHandlerUpdate, ItemHandlersService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import useCustomToast from "@/hooks/useCustomToast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { PasswordInput } from "@/components/ui/password-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { extractErrorMessage } from "@/utils"

function formatDate(dateString: string | undefined | null, localeTag: string) {
  if (!dateString) return null
  return new Date(dateString).toLocaleString(localeTag)
}

function normalizeOptionalText(value: string) {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function parseModelParameters(value: string): Record<string, unknown> {
  const trimmed = value.trim()
  if (!trimmed) {
    return {}
  }
  const parsed = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("模型参数必须是 JSON 对象")
  }
  return parsed as Record<string, unknown>
}

type ModelConfigExample = {
  label: string
  model: string
  apiUrl: string
  parameters: Record<string, unknown>
  note: string
}

const MODEL_CONFIG_EXAMPLES: Record<string, ModelConfigExample> = {
  "openai-gpt5": {
    label: "OpenAI GPT-5",
    model: "openai/gpt-5",
    apiUrl: "",
    parameters: {},
    note: "官方 OpenAI API 可留空 API URL。GPT-5 不要配置 temperature=0.1。",
  },
  "openai-codex": {
    label: "OpenAI GPT-5 Codex",
    model: "openai/gpt-5-codex",
    apiUrl: "",
    parameters: {},
    note: "Codex 使用空参数对象，由模型采用默认采样与推理配置。",
  },
  "deepseek-chat": {
    label: "DeepSeek Chat",
    model: "deepseek/deepseek-chat",
    apiUrl: "https://api.deepseek.com",
    parameters: { temperature: 0.1 },
    note: "DeepSeek Chat 可按需要设置 temperature；这里给出偏稳定的 0.1 示例。",
  },
  "openai-compatible": {
    label: "OpenAI 兼容代理",
    model: "openai/your-model-name",
    apiUrl: "https://your-api.example.com/v1",
    parameters: {},
    note: "模型名前加 openai/，API URL 填兼容接口的 /v1 地址，参数按服务商文档填写。",
  },
}

function ProfileValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 whitespace-pre-wrap text-sm">
        {value || "Not set"}
      </div>
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value?: ReactNode }) {
  const { t } = useI18n()

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="min-w-0 font-mono text-sm">
        {value || t("common.notAvailable")}
      </div>
    </div>
  )
}

export function HandlerSettingsPanel({ itemHandler }: { itemHandler: any }) {
  const queryClient = useQueryClient()
  const { t, localeTag } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const itemHandlerId = String(itemHandler.id)

  const [isEditing, setIsEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [editForm, setEditForm] = useState({
    name: "",
    model: "",
    api_key: "",
    api_url: "",
    model_parameters_json: "{}",
    enabled_skills: [] as string[],
  })

  useEffect(() => {
    setEditForm({
      name: itemHandler.name,
      model: itemHandler.model ?? "",
      api_key: "",
      api_url: itemHandler.api_url ?? "",
      model_parameters_json: JSON.stringify(
        (itemHandler as any).model_parameters ?? {},
        null,
        2,
      ),
      enabled_skills: (itemHandler as any).enabled_skills ?? [],
    })
    setIsEditing(false)
  }, [itemHandler])

  const startEditing = () => {
    setEditForm({
      name: itemHandler.name,
      model: itemHandler.model ?? "",
      api_key: "",
      api_url: itemHandler.api_url ?? "",
      model_parameters_json: JSON.stringify(
        (itemHandler as any).model_parameters ?? {},
        null,
        2,
      ),
      enabled_skills: (itemHandler as any).enabled_skills ?? [],
    })
    setIsEditing(true)
  }

  const cancelEditing = () => {
    setIsEditing(false)
  }

  const saveChanges = async () => {
    const name = editForm.name.trim()
    if (!name) {
      showErrorToast(t("itemHandlers.nameRequired"))
      return
    }

    let modelParameters: Record<string, unknown>
    try {
      modelParameters = parseModelParameters(editForm.model_parameters_json)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "模型参数 JSON 格式不正确",
      )
      return
    }

    const replacementApiKey = normalizeOptionalText(editForm.api_key)
    const requestBody: ItemHandlerUpdate & {
      model_parameters?: Record<string, unknown>
    } = {
      name,
      model: normalizeOptionalText(editForm.model),
      api_url: normalizeOptionalText(editForm.api_url),
      model_parameters: modelParameters,
      enabled_skills: editForm.enabled_skills,
    }
    if (replacementApiKey) {
      requestBody.api_key = replacementApiKey
    }

    setIsSaving(true)
    try {
      await ItemHandlersService.updateItemHandler({
        id: itemHandlerId,
        requestBody,
      })
      setEditForm((current) => ({
        ...current,
        name,
        model: requestBody.model ?? "",
        api_key: "",
        api_url: requestBody.api_url ?? "",
        model_parameters_json: JSON.stringify(
          requestBody.model_parameters ?? {},
          null,
          2,
        ),
      }))
      showSuccessToast(t("itemHandlers.detail.itemHandlerUpdated"))
      setIsEditing(false)
      queryClient.invalidateQueries({
        queryKey: ["itemHandler", itemHandlerId],
      })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
    } catch (error) {
      if (error instanceof ApiError) {
        showErrorToast(extractErrorMessage(error))
      } else {
        showErrorToast(t("itemHandlers.detail.itemHandlerUpdateFailed"))
      }
    } finally {
      setIsSaving(false)
    }
  }

  const [selectedModelExampleKey, setSelectedModelExampleKey] = useState(
    "openai-gpt5",
  )
  const selectedModelExample =
    MODEL_CONFIG_EXAMPLES[selectedModelExampleKey] ??
    MODEL_CONFIG_EXAMPLES["openai-gpt5"]

  const applyModelExample = () => {
    setEditForm((current) => ({
      ...current,
      model: selectedModelExample.model,
      api_url: selectedModelExample.apiUrl,
      model_parameters_json: JSON.stringify(
        selectedModelExample.parameters,
        null,
        2,
      ),
    }))
  }

  return <Card>
  <CardHeader>
    <div className="flex items-center justify-between">
      <div>
        <CardTitle className="flex items-center gap-2">
          <Settings className="size-5" />
          {t("itemHandlers.detail.modelSettings")}
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          {t("itemHandlers.detail.modelSettingsDescription")}
        </p>
      </div>
      <div className="flex gap-2">
        {!isEditing ? (
          <Button size="sm" onClick={startEditing}>
{t("itemHandlers.detail.edit")}
          </Button>
        ) : (
          <>
<Button
  size="sm"
  variant="outline"
  onClick={cancelEditing}
>
  {t("common.cancel")}
</Button>
<Button
  size="sm"
  onClick={saveChanges}
  disabled={isSaving || !editForm.name.trim()}
>
  {isSaving ? t("common.loading") : t("common.save")}
</Button>
          </>
        )}
      </div>
    </div>
  </CardHeader>
  <CardContent className="space-y-4">
    {isEditing ? (
      <>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
<label className="text-sm font-medium">
  {t("common.name")}
</label>
<Input
  value={editForm.name}
  onChange={(e) =>
    setEditForm({ ...editForm, name: e.target.value })
  }
  aria-invalid={!editForm.name.trim()}
  required
/>
          </div>
          <div className="space-y-2">
<label className="text-sm font-medium">
  {t("common.model")}
</label>
<Input
  value={editForm.model}
  onChange={(e) =>
    setEditForm({ ...editForm, model: e.target.value })
  }
  placeholder="e.g., gpt-4"
/>
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
<label className="text-sm font-medium">
  {t("common.apiKey")}
</label>
<PasswordInput
  value={editForm.api_key}
  onChange={(e) =>
    setEditForm({
      ...editForm,
      api_key: e.target.value,
    })
  }
  placeholder={
    (itemHandler as any).has_api_key
      ? t("common.replaceApiKey")
      : t("common.apiKey")
  }
  autoComplete="new-password"
/>
          </div>
          <div className="space-y-2">
<label className="text-sm font-medium">
  {t("common.apiUrl")}
</label>
<Input
  value={editForm.api_url}
  onChange={(e) =>
    setEditForm({
      ...editForm,
      api_url: e.target.value,
    })
  }
  placeholder={t("common.apiUrl")}
/>
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">
模型参数 JSON
          </label>
          <textarea
value={editForm.model_parameters_json}
onChange={(event) =>
  setEditForm({
    ...editForm,
    model_parameters_json: event.target.value,
  })
}
className="min-h-28 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
placeholder="{}"
spellCheck={false}
          />
          <p className="text-xs text-muted-foreground">
留空或填写 {"{}"} 表示不传可选参数。可配置
temperature、reasoning_effort、top_p 等 LiteLLM 参数。
          </p>
        </div>
      </>
    ) : (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <KeyValue
label={t("common.name")}
value={itemHandler.name}
          />
          <KeyValue
label={t("common.model")}
value={itemHandler.model}
          />
          <KeyValue
label={t("common.apiKey")}
value={
  <Badge variant="outline">
    {(itemHandler as any).has_api_key
      ? t("common.apiKeySaved")
      : t("common.noApiKey")}
  </Badge>
}
          />
          <KeyValue
label={t("common.apiUrl")}
value={itemHandler.api_url}
          />
          <div className="sm:col-span-2">
<ProfileValue
  label="模型参数 JSON"
  value={JSON.stringify(
    (itemHandler as any).model_parameters ?? {},
    null,
    2,
  )}
/>
          </div>
        </div>
      </div>
    )}
    <div className="border-t pt-4 mt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <KeyValue label={t("common.id")} value={itemHandler.id} />
        <KeyValue
          label={t("common.ownerId")}
          value={itemHandler.owner_id}
        />
        <KeyValue
          label={t("common.createdAt")}
          value={
formatDate(itemHandler.created_at, localeTag) ||
undefined
          }
        />
        <KeyValue
          label={t("common.updatedAt")}
          value={
formatDate(itemHandler.updated_at, localeTag) ||
undefined
          }
        />
      </div>
    </div>
    <div className="mt-4 border-t pt-4">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full max-w-sm space-y-2">
          <label className="text-sm font-semibold">配置示例</label>
          <Select
value={selectedModelExampleKey}
onValueChange={setSelectedModelExampleKey}
          >
<SelectTrigger>
  <SelectValue />
</SelectTrigger>
<SelectContent>
  {Object.entries(MODEL_CONFIG_EXAMPLES).map(
    ([key, example]) => (
      <SelectItem key={key} value={key}>
        {example.label}
      </SelectItem>
    ),
  )}
</SelectContent>
          </Select>
        </div>
        {isEditing && (
          <Button
type="button"
variant="outline"
onClick={applyModelExample}
          >
应用到当前表单
          </Button>
        )}
      </div>
      <div className="grid gap-3 text-sm lg:grid-cols-3">
        <div className="min-w-0">
          <div className="mb-1 text-xs text-muted-foreground">
Model
          </div>
          <code
className="block truncate font-mono"
title={selectedModelExample.model}
          >
{selectedModelExample.model}
          </code>
        </div>
        <div className="min-w-0">
          <div className="mb-1 text-xs text-muted-foreground">
API URL
          </div>
          <code
className="block truncate font-mono"
title={selectedModelExample.apiUrl || "留空"}
          >
{selectedModelExample.apiUrl || "留空"}
          </code>
        </div>
        <div className="min-w-0">
          <div className="mb-1 text-xs text-muted-foreground">
模型参数
          </div>
          <code
className="block truncate font-mono"
title={JSON.stringify(selectedModelExample.parameters)}
          >
{JSON.stringify(selectedModelExample.parameters)}
          </code>
        </div>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {selectedModelExample.note}
      </p>
    </div>
  </CardContent>
</Card>
}
