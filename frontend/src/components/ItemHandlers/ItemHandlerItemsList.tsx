import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { ItemHandlerAssociationsService, type ItemPublic } from "@/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import useCustomToast from "@/hooks/useCustomToast";
import { handleError } from "@/utils";

interface ItemHandlerItemsListProps {
  itemHandlerId: string;
}

const ItemHandlerItemsList = ({ itemHandlerId }: ItemHandlerItemsListProps) => {
  const queryClient = useQueryClient();
  const { showSuccessToast, showErrorToast } = useCustomToast();
  const [isLoading, setIsLoading] = useState(false);

  const { data: items, isLoading: isItemsLoading } = useQuery({
    queryFn: () => ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: [`itemHandler-${itemHandlerId}-items`],
  });

  const mutation = useMutation({
    mutationFn: (itemId: string) => 
      ItemHandlerAssociationsService.removeItemFromHandler({ itemHandlerId, itemId }),
    onSuccess: () => {
      showSuccessToast("Item removed from item handler successfully");
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [`itemHandler-${itemHandlerId}-items`] });
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] });
      queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  const handleRemoveItem = (itemId: string) => {
    if (confirm("Are you sure you want to remove this item from the handler?")) {
      mutation.mutate(itemId);
    }
  };

  if (isItemsLoading) {
    return <div className="p-4 text-muted-foreground">Loading items...</div>;
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Associated Items</CardTitle>
        <CardDescription>Items linked to this item handler</CardDescription>
      </CardHeader>
      <CardContent>
        {items?.length === 0 ? (
          <div className="p-4 text-muted-foreground">No items associated with this handler.</div>
        ) : (
          <div className="space-y-4">
            {items?.map((item: ItemPublic) => (
              <div key={item.id} className="flex items-center justify-between p-2 rounded-md hover:bg-muted transition-colors">
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-sm text-muted-foreground">{item.description || "No description"}</div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive/90 hover:bg-destructive/10"
                  onClick={() => handleRemoveItem(item.id)}
                  disabled={mutation.isPending}
                >
                  <Trash2 className="h-4 w-4" />
                  <span className="sr-only">Remove item</span>
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ItemHandlerItemsList;