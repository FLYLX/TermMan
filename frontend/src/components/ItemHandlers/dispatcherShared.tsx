import { Button } from "@/components/ui/button"
import { useI18n } from "@/components/locale-provider"

export const LIST_PAGE_SIZE = 10

export function LoadMoreButton({
  remainingCount,
  onClick,
  className,
}: {
  remainingCount: number
  onClick: () => void
  className?: string
}) {
  const { locale } = useI18n()
  const nextCount = Math.min(LIST_PAGE_SIZE, remainingCount)

  if (remainingCount <= 0) {
    return null
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={onClick}
    >
      {locale === "zh" ? `再显示 ${nextCount} 条` : `Show ${nextCount} more`}
    </Button>
  )
}

