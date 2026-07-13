import { Check, Copy, Eye, EyeOff } from "lucide-react"
import { useState } from "react"

import { useI18n } from "@/components/locale-provider"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
import { Button } from "./button"

type SecretValueProps = {
  value?: string | null
  label?: string
  emptyText?: string
  className?: string
  compact?: boolean
}

function maskSecret(value: string) {
  if (value.length <= 4) {
    return "••••"
  }
  return `••••${value.slice(-4)}`
}

export function SecretValue({
  value,
  label = "API Key",
  emptyText,
  className,
  compact = false,
}: SecretValueProps) {
  const { t } = useI18n()
  const [revealed, setRevealed] = useState(false)
  const [copiedText, copy] = useCopyToClipboard()
  const normalizedValue = String(value ?? "")
  const isCopied = Boolean(normalizedValue) && copiedText === normalizedValue

  if (!normalizedValue) {
    return (
      <span className={cn("italic text-muted-foreground", className)}>
        {emptyText || t("common.notAvailable")}
      </span>
    )
  }

  return (
    <div className={cn("flex min-w-0 items-center gap-1", className)}>
      <span
        className={cn(
          "min-w-0 font-mono text-sm",
          revealed ? "break-all" : "truncate",
          compact && "max-w-36",
        )}
      >
        {revealed ? normalizedValue : maskSecret(normalizedValue)}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7 shrink-0"
        onClick={(event) => {
          event.stopPropagation()
          setRevealed((current) => !current)
        }}
        aria-label={
          revealed ? t("common.hideSecret") : t("common.showSecret")
        }
        title={revealed ? t("common.hideSecret") : t("common.showSecret")}
      >
        {revealed ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7 shrink-0"
        onClick={(event) => {
          event.stopPropagation()
          void copy(normalizedValue)
        }}
        aria-label={t("common.copyLabel", { label })}
        title={t("common.copyLabel", { label })}
      >
        {isCopied ? (
          <Check className="size-3.5 text-emerald-500" />
        ) : (
          <Copy className="size-3.5" />
        )}
      </Button>
    </div>
  )
}
