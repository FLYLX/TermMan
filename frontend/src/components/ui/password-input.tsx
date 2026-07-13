import * as React from "react"
import { Check, Copy, Eye, EyeOff } from "lucide-react"

import { useI18n } from "@/components/locale-provider"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
import { Button } from "./button"

interface PasswordInputProps extends React.ComponentProps<"input"> {
  error?: string
  copyable?: boolean
  copyLabel?: string
}

const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  (
    {
      className,
      error,
      copyable = false,
      copyLabel = "Copy value",
      value,
      ...props
    },
    ref,
  ) => {
    const [showPassword, setShowPassword] = React.useState(false)
    const { t } = useI18n()
    const [copiedText, copy] = useCopyToClipboard()
    const copyValue = String(value ?? "")
    const isCopied = Boolean(copyValue) && copiedText === copyValue

    return (
      <div className="relative">
        <input
          type={showPassword ? "text" : "password"}
          data-slot="input"
          className={cn(
            "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
            "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
            "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
            copyable ? "pr-20" : "pr-10",
            className,
          )}
          ref={ref}
          aria-invalid={!!error}
          value={value}
          {...props}
        />
        {copyable ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="absolute right-9 top-0 h-full px-2 py-2 hover:bg-transparent"
            onClick={() => void copy(copyValue)}
            disabled={!copyValue}
            aria-label={copyLabel}
            title={copyLabel}
          >
            {isCopied ? (
              <Check className="h-4 w-4 text-emerald-500" />
            ) : (
              <Copy className="h-4 w-4 text-muted-foreground" />
            )}
          </Button>
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
          onClick={() => setShowPassword(!showPassword)}
          aria-label={
            showPassword ? t("common.hideSecret") : t("common.showSecret")
          }
          title={
            showPassword ? t("common.hideSecret") : t("common.showSecret")
          }
        >
          {showPassword ? (
            <EyeOff className="h-4 w-4 text-muted-foreground" />
          ) : (
            <Eye className="h-4 w-4 text-muted-foreground" />
          )}
        </Button>
      </div>
    )
  }
)

PasswordInput.displayName = "PasswordInput"

export { PasswordInput }
