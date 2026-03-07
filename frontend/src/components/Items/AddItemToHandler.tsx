import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ItemHandlersService, ItemHandlerAssociationsService } from "@/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingButton } from "@/components/ui/loading-button";
import useCustomToast from "@/hooks/useCustomToast";
import { handleError } from "@/utils";

interface AddItemToHandlerProps {
  itemId: string;
}

const formSchema = z.object({
  itemHandlerId: z.string().min(1, { message: "Item Handler is required" }),
});

type FormData = z.infer<typeof formSchema>;

const AddItemToHandler = ({ itemId }: AddItemToHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const queryClient = useQueryClient();
  const { showSuccessToast, showErrorToast } = useCustomToast();

  const { data: itemHandlers } = useQuery({
    queryFn: () => ItemHandlersService.readItemHandlers({ skip: 0, limit: 100 }),
    queryKey: ["itemHandlers"],
  });

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      itemHandlerId: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      ItemHandlerAssociationsService.addItemToHandler({
        requestBody: { item_handler_id: data.itemHandlerId, item_id: itemId },
      }),
    onSuccess: () => {
      showSuccessToast("Item added to item handler successfully");
      form.reset();
      setIsOpen(false);
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] });
      queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  const onSubmit = (data: FormData) => {
    mutation.mutate(data);
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="flex items-center gap-1">
          <Link2 className="h-4 w-4" />
          Add to Handler
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Item to Handler</DialogTitle>
          <DialogDescription>
            Select an item handler to associate with this item.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="itemHandlerId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Item Handler <span className="text-destructive">*</span>
                    </FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={mutation.isPending}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select an item handler" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {itemHandlers?.map((handler) => (
                          <SelectItem key={handler.id} value={handler.id}>
                            {handler.name} (ID: {handler.id.slice(0, 8)}...)
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                Add
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
};

export default AddItemToHandler;