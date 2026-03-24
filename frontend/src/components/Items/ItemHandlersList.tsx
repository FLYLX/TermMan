import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"

import { type ItemHandler, ItemHandlerAssociationsService } from "@/client"
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
  const { showSuccessToast, showErrorToast } = useCustomToast()

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
      showSuccessToast("Item removed from item handler successfully")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [`item-${itemId}-handlers`] })
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
      queryClient.invalidateQueries({ queryKey: ["items"] })
    },
  })

  const handleRemoveHandler = (itemHandlerId: string) => {
    if (
      confirm("Are you sure you want to remove this handler from the item?")
    ) {
      mutation.mutate(itemHandlerId)
    }
  }

  if (isHandlersLoading) {
    return <div className="p-4 text-muted-foreground">Loading handlers...</div>
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Associated Item Handlers</CardTitle>
        <CardDescription>Item handlers linked to this item</CardDescription>
      </CardHeader>
      <CardContent>
        {handlers?.length === 0 ? (
          <div className="p-4 text-muted-foreground">
            No item handlers associated with this item.
          </div>
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
                    {handler.model || "No model"}
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
                  <span className="sr-only">Remove handler</span>
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
