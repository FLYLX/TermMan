import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"

import { type ItemHandler, ItemHandlerAssociationsService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface ItemHandlersListProps {
  itemId: string
}

const ItemHandlersList = ({ itemId }: ItemHandlersListProps) => {
  const queryClient = useQueryClient()
  const { locale } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const copy =
    locale === "zh"
      ? {
          removed: "终端已从 TermHandler 中移除",
          confirm: "确认将这个 TermHandler 从当前终端中移除吗？",
          loading: "正在加载 TermHandler...",
          title: "关联的 TermHandler",
          description: "当前终端已连接的 TermHandler",
          empty: "当前终端还没有关联任何 TermHandler。",
          noModel: "未配置模型",
          remove: "移除 TermHandler",
        }
      : {
          removed: "Terminal removed from TermHandler successfully",
          confirm: "Remove this TermHandler from the current terminal?",
          loading: "Loading TermHandlers...",
          title: "Attached TermHandlers",
          description: "TermHandlers currently linked to this terminal",
          empty: "No TermHandlers are linked to this terminal yet.",
          noModel: "No model",
          remove: "Remove TermHandler",
        }

  const { data: handlers, isLoading: isHandlersLoading } = useQuery({
    queryFn: () =>
      ItemHandlerAssociationsService.getHandlersForItem({ itemId }),
    queryKey: [`item-${itemId}-handlers`],
  })

  const mutation = useMutation({
    mutationFn: (itemHandlerId: string) =>
      ItemHandlerAssociationsService.removeItemFromHandler({
        itemHandlerId,
        itemId,
      }),
    onSuccess: () => {
      showSuccessToast(copy.removed)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [`item-${itemId}-handlers`] })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const handleRemoveHandler = (itemHandlerId: string) => {
    if (confirm(copy.confirm)) {
      mutation.mutate(itemHandlerId)
    }
  }

  if (isHandlersLoading) {
    return <div className="p-4 text-muted-foreground">{copy.loading}</div>
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent>
        {handlers?.length === 0 ? (
          <div className="p-4 text-muted-foreground">{copy.empty}</div>
        ) : (
          <div className="space-y-4">
            {handlers?.map((handler: ItemHandler, index) => (
              <div
                key={handler.id ?? index}
                className="flex items-center justify-between p-2 rounded-md hover:bg-muted transition-colors"
              >
                <div>
                  <div className="font-medium">{handler.name}</div>
                  <div className="text-sm text-muted-foreground">
                    {handler.model || copy.noModel}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive/90 hover:bg-destructive/10"
                  onClick={() => handler.id && handleRemoveHandler(handler.id)}
                  disabled={mutation.isPending}
                >
                  <Trash2 className="h-4 w-4" />
                  <span className="sr-only">{copy.remove}</span>
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default ItemHandlersList
