import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"

import { type Item, ItemHandlerAssociationsService } from "@/client"
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

interface ItemHandlerItemsListProps {
  itemHandlerId: string
}

const ItemHandlerItemsList = ({ itemHandlerId }: ItemHandlerItemsListProps) => {
  const queryClient = useQueryClient()
  const { locale } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const copy =
    locale === "zh"
      ? {
          removed: "终端已从 TermHandler 中移除",
          confirm: "确认将这个终端从当前 TermHandler 中移除吗？",
          loading: "正在加载终端...",
          title: "关联的终端",
          description: "当前 TermHandler 已连接的终端",
          empty: "当前 TermHandler 还没有关联任何终端。",
          noDescription: "暂无备注",
          remove: "移除终端",
        }
      : {
          removed: "Terminal removed from TermHandler successfully",
          confirm: "Remove this terminal from the current TermHandler?",
          loading: "Loading terminals...",
          title: "Attached Terminals",
          description: "Terminals linked to this TermHandler",
          empty: "No terminals are linked to this TermHandler yet.",
          noDescription: "No description",
          remove: "Remove terminal",
        }

  const { data: items, isLoading: isItemsLoading } = useQuery({
    queryFn: () =>
      ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: [`itemHandler-${itemHandlerId}-items`],
  })

  const mutation = useMutation({
    mutationFn: (itemId: string) =>
      ItemHandlerAssociationsService.removeItemFromHandler({
        itemHandlerId,
        itemId,
      }),
    onSuccess: () => {
      showSuccessToast(copy.removed)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: [`itemHandler-${itemHandlerId}-items`],
      })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const handleRemoveItem = (itemId: string) => {
    if (confirm(copy.confirm)) {
      mutation.mutate(itemId)
    }
  }

  if (isItemsLoading) {
    return <div className="p-4 text-muted-foreground">{copy.loading}</div>
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent>
        {items?.length === 0 ? (
          <div className="p-4 text-muted-foreground">{copy.empty}</div>
        ) : (
          <div className="space-y-4">
            {items?.map((item: Item, index) => (
              <div
                key={item.id ?? index}
                className="flex items-center justify-between p-2 rounded-md hover:bg-muted transition-colors"
              >
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-sm text-muted-foreground">
                    {item.description || copy.noDescription}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive/90 hover:bg-destructive/10"
                  onClick={() => item.id && handleRemoveItem(item.id)}
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

export default ItemHandlerItemsList
