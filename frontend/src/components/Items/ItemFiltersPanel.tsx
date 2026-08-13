import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Filter,
  Loader2,
  Play,
  RefreshCw,
  Shield,
  Terminal,
} from "lucide-react"

import { type ItemUpdate, ItemsService } from "@/client"
import { FilterGeneratorCard } from "@/components/Items/FilterGeneratorCard"
import {
  type FilterRule,
  FilterRuleEditor,
} from "@/components/Items/FilterRuleEditor"
import { useI18n } from "@/components/locale-provider"
import useCustomToast from "@/hooks/useCustomToast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

function createDefaultInputRules(): Record<string, FilterRule> {
  return {
    block_filter: {
      regex_patterns: ["violence|porn|gambling", "http://.*\\.exe"],
      action_type: "block",
    },
    ignore_filter: {
      regex_patterns: [
        "^\\s*$",
        "^\\x1b\\[[0-9;]*[a-zA-Z]$",
        "^\\r$",
        "\\d+%",
        "\\[\\s*=+\\s*\\]",
        "\\.\\.\\.+",
        "DEBUG\\s*:",
        "INFO\\s*:",
      ],
      action_type: "ignore",
    },
    log_filter: {
      regex_patterns: [
        "error:",
        "failed:",
        "exception:",
        "Error:",
        "FAILED",
        "EXCEPTION",
        "warning:",
        "warn:",
        "Warning:",
        "WARN",
        "\\(y/n\\)",
        "\\[Y/n\\]",
        "enter.*:",
        "password:",
        "confirm",
      ],
      action_type: "log",
    },
    replace_filter: {
      regex_patterns: [
        "^\\d{11}$",
        "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
      ],
      action_type: "replace",
      action: {
        replace_rules: {
          "^\\d{11}$": "***phone***",
          "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}": "***email***",
        },
      },
    },
  }
}

function createDefaultOutputRules(): Record<string, FilterRule> {
  return {
    block_filter: {
      regex_patterns: [
        "rm\\s+-rf\\s+/",
        "rm\\s+-rf\\s+~",
        "mkfs",
        "dd\\s+if=",
        ">\\s*/dev/sd",
        ":\\(\\)\\s*\\{\\s*:\\|\\:&\\s*\\}\\s*;:",
        "chmod\\s+777\\s+/",
        "chown\\s+.*:.*\\s+/",
        "shutdown",
        "reboot",
        "init\\s+0",
        "init\\s+6",
        "halt",
        "poweroff",
      ],
      action_type: "block",
    },
    ignore_filter: {
      regex_patterns: ["DEBUG\\s*:", "INFO\\s*:"],
      action_type: "ignore",
    },
    log_filter: {
      regex_patterns: ["sudo\\s+", "chmod\\s+", "chown\\s+"],
      action_type: "log",
    },
    replace_filter: {
      regex_patterns: [
        "password\\s*=\\s*\\S+",
        "api[_-]?key\\s*=\\s*\\S+",
        "secret\\s*=\\s*\\S+",
        "token\\s*=\\s*\\S+",
        "--password\\s+\\S+",
        "-p\\s+\\S+",
      ],
      action_type: "replace",
      action: {
        replace_rules: {
          "password\\s*=\\s*\\S+": "password=***",
          "api[_-]?key\\s*=\\s*\\S+": "api_key=***",
          "secret\\s*=\\s*\\S+": "secret=***",
          "token\\s*=\\s*\\S+": "token=***",
          "--password\\s+\\S+": "--password ***",
          "-p\\s+\\S+": "-p ***",
        },
      },
    },
  }
}

function serializeFilterState(
  enabled: boolean,
  rules: Record<string, FilterRule>,
) {
  return JSON.stringify({ enabled, rules })
}

function getInputFilterRules(item: any): Record<string, FilterRule> {
  return item?.input_filter_rules &&
    Object.keys(item.input_filter_rules).length > 0
    ? (item.input_filter_rules as Record<string, FilterRule>)
    : createDefaultInputRules()
}

function getOutputFilterRules(item: any): Record<string, FilterRule> {
  return item?.output_filter_rules &&
    Object.keys(item.output_filter_rules).length > 0
    ? (item.output_filter_rules as Record<string, FilterRule>)
    : createDefaultOutputRules()
}

export function ItemFiltersPanel({ itemId }: { itemId: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: item } = useQuery({
    queryKey: ["items", "detail", itemId],
    queryFn: () => ItemsService.readItem({ id: itemId }),
    select: (data) => data as any,
  })

  const [inputFilterEnabled, setInputFilterEnabled] = useState(false)
  const [inputFilterRules, setInputFilterRules] = useState<
    Record<string, FilterRule>
  >(createDefaultInputRules())
  const [outputFilterEnabled, setOutputFilterEnabled] = useState(false)
  const [outputFilterRules, setOutputFilterRules] = useState<
    Record<string, FilterRule>
  >(createDefaultOutputRules())

  const [inputTestText, setInputTestText] = useState("")
  const [inputTestResult, setInputTestResult] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [isTestingInputFilter, setIsTestingInputFilter] = useState(false)
  const [outputTestCommand, setOutputTestCommand] = useState("")
  const [outputTestResult, setOutputTestResult] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [isTestingOutputFilter, setIsTestingOutputFilter] = useState(false)

  const inputSignature = useMemo(
    () => serializeFilterState(inputFilterEnabled, inputFilterRules),
    [inputFilterEnabled, inputFilterRules],
  )
  const outputSignature = useMemo(
    () => serializeFilterState(outputFilterEnabled, outputFilterRules),
    [outputFilterEnabled, outputFilterRules],
  )
  const inputSyncedSignatureRef = useRef("")
  const outputSyncedSignatureRef = useRef("")
  const initializedRef = useRef(false)

  useEffect(() => {
    if (!item || initializedRef.current) {
      return
    }
    initializedRef.current = true
    setInputFilterEnabled(item.input_filter_enabled || false)
    setInputFilterRules(getInputFilterRules(item))
    setOutputFilterEnabled(item.output_filter_enabled || false)
    setOutputFilterRules(getOutputFilterRules(item))
    inputSyncedSignatureRef.current = serializeFilterState(
      item.input_filter_enabled || false,
      getInputFilterRules(item),
    )
    outputSyncedSignatureRef.current = serializeFilterState(
      item.output_filter_enabled || false,
      getOutputFilterRules(item),
    )
  }, [item])

  // Debounced auto-save for input filter
  useEffect(() => {
    if (!initializedRef.current) {
      return
    }
    if (inputSignature === inputSyncedSignatureRef.current) {
      return
    }
    const timer = window.setTimeout(async () => {
      const payloadSignature = inputSignature
      const updateData: ItemUpdate = {
        input_filter_enabled: inputFilterEnabled,
        input_filter_rules: inputFilterRules,
      }
      try {
        const updatedItem = await ItemsService.updateItem({
          id: itemId,
          requestBody: updateData,
        })
        inputSyncedSignatureRef.current = serializeFilterState(
          updatedItem.input_filter_enabled || false,
          getInputFilterRules(updatedItem),
        )
        if (payloadSignature === inputSignature) {
          queryClient.setQueryData(["items", "detail", itemId], updatedItem)
        }
      } catch (error) {
        showErrorToast(t("items.detail.inputFilterSaveFailed"))
      }
    }, 600)
    return () => window.clearTimeout(timer)
  }, [
    inputFilterEnabled,
    inputFilterRules,
    inputSignature,
    itemId,
    queryClient,
    showErrorToast,
    t,
  ])

  // Debounced auto-save for output filter
  useEffect(() => {
    if (!initializedRef.current) {
      return
    }
    if (outputSignature === outputSyncedSignatureRef.current) {
      return
    }
    const timer = window.setTimeout(async () => {
      const payloadSignature = outputSignature
      const updateData: ItemUpdate = {
        output_filter_enabled: outputFilterEnabled,
        output_filter_rules: outputFilterRules,
      }
      try {
        const updatedItem = await ItemsService.updateItem({
          id: itemId,
          requestBody: updateData,
        })
        outputSyncedSignatureRef.current = serializeFilterState(
          updatedItem.output_filter_enabled || false,
          getOutputFilterRules(updatedItem),
        )
        if (payloadSignature === outputSignature) {
          queryClient.setQueryData(["items", "detail", itemId], updatedItem)
        }
      } catch (error) {
        showErrorToast(t("items.detail.outputFilterSaveFailed"))
      }
    }, 600)
    return () => window.clearTimeout(timer)
  }, [
    outputFilterEnabled,
    outputFilterRules,
    outputSignature,
    itemId,
    queryClient,
    showErrorToast,
    t,
  ])

  const handleTestInputFilter = async () => {
    if (!inputTestText.trim()) {
      showErrorToast(t("items.detail.enterTestText"))
      return
    }
    setIsTestingInputFilter(true)
    try {
      const result = await ItemsService.testInputFilter({
        id: itemId,
        requestBody: { test_text: inputTestText },
      })
      setInputTestResult(result)
    } catch (error) {
      showErrorToast(t("items.detail.inputFilterTestFailed"))
    } finally {
      setIsTestingInputFilter(false)
    }
  }

  const handleTestOutputFilter = async () => {
    if (!outputTestCommand.trim()) {
      showErrorToast(t("items.detail.enterTestCommand"))
      return
    }
    setIsTestingOutputFilter(true)
    try {
      const result = await ItemsService.testOutputFilter({
        id: itemId,
        requestBody: { command: outputTestCommand },
      })
      setOutputTestResult(result)
    } catch (error) {
      showErrorToast(t("items.detail.outputFilterTestFailed"))
    } finally {
      setIsTestingOutputFilter(false)
    }
  }

  const handleSyncInputFilterRules = async () => {
    initializedRef.current = false
    await queryClient.invalidateQueries({
      queryKey: ["items", "detail", itemId],
    })
    showSuccessToast("已同步后端过滤规则")
  }

  if (!item) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> 正在加载过滤器配置…
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-2">
            <Filter className="mt-1 size-5 text-blue-500" />
            <div>
              <h2 className="text-xl font-semibold">
                {t("items.detail.inputFilterSettings")}
              </h2>
              <p className="text-xs text-muted-foreground">
                {t("items.detail.inputFilterFlowDescription")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-sm font-medium">{t("common.enabled")}</span>
            <button
              type="button"
              onClick={() => setInputFilterEnabled(!inputFilterEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                inputFilterEnabled ? "bg-blue-500" : "bg-muted"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  inputFilterEnabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </div>

        <div className="mb-4 rounded-xl border bg-muted/20 p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Filter className="size-4 text-blue-500" />
                <span>Agent 噪声过滤规则</span>
                <Badge variant="outline" className="text-[10px]">
                  {Object.keys(inputFilterRules).length}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Agent 通过 MCP 写入的规则会显示在下面。
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void handleSyncInputFilterRules()}
            >
              <RefreshCw className="mr-2 size-4" />
              同步后端规则
            </Button>
          </div>
        </div>

        <FilterGeneratorCard
          itemId={itemId}
          target="input"
          currentRules={inputFilterRules}
          onApply={setInputFilterRules}
        />

        <FilterRuleEditor
          value={inputFilterRules}
          onChange={setInputFilterRules}
          defaultRules={createDefaultInputRules()}
        />

        <div className="mt-4 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
          <div className="mb-3 flex items-center gap-2">
            <Terminal className="size-4 text-blue-500" />
            <span className="text-sm font-medium">
              {t("items.detail.testInputFilter")}
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t("items.detail.inputText")}
              </Label>
              <Textarea
                placeholder={t("items.detail.pasteTerminalOutput")}
                className="h-40 font-mono text-xs"
                value={inputTestText}
                onChange={(e) => setInputTestText(e.target.value)}
              />
              <Button
                size="sm"
                onClick={handleTestInputFilter}
                disabled={isTestingInputFilter}
                className="w-full"
              >
                {isTestingInputFilter ? (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                ) : (
                  <Play className="mr-2 size-4" />
                )}
                {t("items.detail.testFilter")}
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t("items.detail.filterResult")}
              </Label>
              <div className="h-40 overflow-auto rounded-md border bg-muted/30 p-3">
                {inputTestResult ? (
                  <pre className="whitespace-pre-wrap text-xs font-mono">
                    {String(inputTestResult.result || "")}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {t("items.detail.clickTestFilter")}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-2">
            <Shield className="mt-1 size-5 text-orange-500" />
            <div>
              <h2 className="text-xl font-semibold">
                {t("items.detail.outputFilterSettings")}
              </h2>
              <p className="text-xs text-muted-foreground">
                {t("items.detail.outputFilterFlowDescription")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-sm font-medium">{t("common.enabled")}</span>
            <button
              type="button"
              onClick={() => setOutputFilterEnabled(!outputFilterEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                outputFilterEnabled ? "bg-orange-500" : "bg-muted"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  outputFilterEnabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </div>

        <FilterGeneratorCard
          itemId={itemId}
          target="output"
          currentRules={outputFilterRules}
          onApply={setOutputFilterRules}
        />

        <FilterRuleEditor
          value={outputFilterRules}
          onChange={setOutputFilterRules}
          defaultRules={createDefaultOutputRules()}
        />

        <div className="mt-4 rounded-lg border border-orange-500/30 bg-orange-500/5 p-4">
          <div className="mb-3 flex items-center gap-2">
            <Shield className="size-4 text-orange-500" />
            <span className="text-sm font-medium">
              {t("items.detail.testOutputFilter")}
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t("items.detail.commandToTest")}
              </Label>
              <Textarea
                placeholder={t("items.detail.enterCommandToTest")}
                className="h-32 font-mono text-xs"
                value={outputTestCommand}
                onChange={(e) => setOutputTestCommand(e.target.value)}
              />
              <Button
                size="sm"
                onClick={handleTestOutputFilter}
                disabled={isTestingOutputFilter}
                className="w-full"
              >
                {isTestingOutputFilter ? (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                ) : (
                  <Play className="mr-2 size-4" />
                )}
                {t("items.detail.testCommand")}
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t("items.detail.filterResult")}
              </Label>
              <div className="h-32 overflow-auto rounded-md border bg-muted/30 p-3">
                {outputTestResult ? (
                  <pre className="whitespace-pre-wrap text-xs font-mono">
                    {String(outputTestResult.result || "")}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {t("items.detail.clickTestCommand")}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
