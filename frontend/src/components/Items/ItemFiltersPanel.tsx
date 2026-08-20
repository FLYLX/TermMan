import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Filter, Loader2, Play, Shield } from "lucide-react"

import { type ItemUpdate, ItemsService } from "@/client"
import { FilterGeneratorDialog } from "@/components/Items/FilterGeneratorCard"
import {
  type FilterRule,
  FilterRuleEditor,
} from "@/components/Items/FilterRuleEditor"
import { SketchDialog } from "@/components/Items/SketchDialog"
import { useI18n } from "@/components/locale-provider"
import useCustomToast from "@/hooks/useCustomToast"
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

interface FilterTestDialogProps {
  title: string
  description: string
  inputLabel: string
  inputPlaceholder: string
  onRun: (text: string) => Promise<Record<string, unknown>>
}

function FilterTestDialog({
  title,
  description,
  inputLabel,
  inputPlaceholder,
  onRun,
}: FilterTestDialogProps) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [running, setRunning] = useState(false)

  const handleRun = async () => {
    if (!text.trim()) {
      return
    }
    setRunning(true)
    try {
      setResult(await onRun(text))
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setOpen(true)}
      >
        <Play className="mr-2 size-4" />
        测试
      </Button>
      <SketchDialog open={open} onClose={() => setOpen(false)} title={title} description={description}>
        <div className="space-y-3">
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">
              {inputLabel}
            </Label>
            <Textarea
              placeholder={inputPlaceholder}
              className="h-40 font-mono text-xs"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <Button
            size="sm"
            onClick={handleRun}
            disabled={running || !text.trim()}
            className="w-full"
          >
            {running ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Play className="mr-2 size-4" />
            )}
            运行测试
          </Button>
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">结果</Label>
            <div className="h-40 overflow-auto rounded-md border bg-muted/30 p-3">
              {result ? (
                <pre className="whitespace-pre-wrap text-xs font-mono">
                  {String(result.result || "")}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">
                  运行测试后结果显示在这里
                </p>
              )}
            </div>
          </div>
        </div>
      </SketchDialog>
    </>
  )
}

export function ItemFiltersPanel({ itemId }: { itemId: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: item } = useQuery({
    queryKey: ["items", "detail", itemId],
    queryFn: () => ItemsService.readItem({ id: itemId }),
    select: (data) => data as any,
    refetchInterval: 5000,
  })

  const [inputFilterEnabled, setInputFilterEnabled] = useState(false)
  const [inputFilterRules, setInputFilterRules] = useState<
    Record<string, FilterRule>
  >(createDefaultInputRules())
  const [outputFilterEnabled, setOutputFilterEnabled] = useState(false)
  const [outputFilterRules, setOutputFilterRules] = useState<
    Record<string, FilterRule>
  >(createDefaultOutputRules())

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

  // Adopt server state on first load and whenever the local state is clean
  // (i.e. not being edited), so Agent/MCP-side rule changes appear without a
  // manual sync button.
  useEffect(() => {
    if (!item) {
      return
    }
    const serverInputEnabled = item.input_filter_enabled || false
    const serverInputRules = getInputFilterRules(item)
    const serverOutputEnabled = item.output_filter_enabled || false
    const serverOutputRules = getOutputFilterRules(item)

    if (!initializedRef.current) {
      initializedRef.current = true
      setInputFilterEnabled(serverInputEnabled)
      setInputFilterRules(serverInputRules)
      setOutputFilterEnabled(serverOutputEnabled)
      setOutputFilterRules(serverOutputRules)
    } else {
      if (inputSyncedSignatureRef.current === inputSignature) {
        setInputFilterEnabled(serverInputEnabled)
        setInputFilterRules(serverInputRules)
      }
      if (outputSyncedSignatureRef.current === outputSignature) {
        setOutputFilterEnabled(serverOutputEnabled)
        setOutputFilterRules(serverOutputRules)
      }
    }
    inputSyncedSignatureRef.current = serializeFilterState(
      serverInputEnabled,
      serverInputRules,
    )
    outputSyncedSignatureRef.current = serializeFilterState(
      serverOutputEnabled,
      serverOutputRules,
    )
  }, [item, inputSignature, outputSignature])

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

  const [target, setTarget] = useState<"input" | "output">("input")

  if (!item) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> 正在加载过滤器配置…
      </div>
    )
  }

  const isInput = target === "input"
  const enabled = isInput ? inputFilterEnabled : outputFilterEnabled
  const setEnabled = isInput ? setInputFilterEnabled : setOutputFilterEnabled

  return (
    <div className="space-y-4">
      <div className="flex justify-center">
        <div className="inline-flex rounded-full border-2 border-[#3a3a3a] bg-white p-1 shadow-[3px_4px_0_rgba(0,0,0,0.10)]">
          {(
            [
              { key: "input", label: "终端 → Agent", icon: Filter },
              { key: "output", label: "Agent → 终端", icon: Shield },
            ] as const
          ).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTarget(key)}
              className={`flex items-center gap-2 rounded-full px-5 py-2 text-sm font-bold transition-all ${
                target === key
                  ? "bg-[#3a3a3a] text-white"
                  : "text-[#565654] hover:bg-muted"
              }`}
            >
              <Icon className="size-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-end gap-2">
          <FilterGeneratorDialog
            itemId={itemId}
            target={target}
            currentRules={isInput ? inputFilterRules : outputFilterRules}
            onApply={isInput ? setInputFilterRules : setOutputFilterRules}
          />
          <FilterTestDialog
            title={
              isInput
                ? t("items.detail.testInputFilter")
                : t("items.detail.testOutputFilter")
            }
            description={
              isInput
                ? "粘贴一段终端输出，查看经过滤后 Agent 实际看到的内容。"
                : "输入一条命令，查看过滤器判定结果。"
            }
            inputLabel={
              isInput
                ? t("items.detail.inputText")
                : t("items.detail.commandToTest")
            }
            inputPlaceholder={
              isInput
                ? t("items.detail.pasteTerminalOutput")
                : t("items.detail.enterCommandToTest")
            }
            onRun={async (text) =>
              isInput
                ? ItemsService.testInputFilter({
                    id: itemId,
                    requestBody: { test_text: text },
                  })
                : ItemsService.testOutputFilter({
                    id: itemId,
                    requestBody: { command: text },
                  })
            }
          />
          <span className="text-sm font-medium">{t("common.enabled")}</span>
          <button
            type="button"
            onClick={() => setEnabled(!enabled)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              enabled ? "bg-[#3a3a3a]" : "bg-muted"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>

        <FilterRuleEditor
          key={target}
          value={isInput ? inputFilterRules : outputFilterRules}
          onChange={isInput ? setInputFilterRules : setOutputFilterRules}
          defaultRules={
            isInput ? createDefaultInputRules() : createDefaultOutputRules()
          }
        />
      </section>
    </div>
  )
}
