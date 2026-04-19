import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"

import { ItemHandlersService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface DeleteItemHandlerProps {
  id: string
  onSuccess: () => void
}

const DeleteItemHandler = ({ id, onSuccess }: DeleteItemHandlerProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: () => ItemHandlersService.deleteItemHandler({ id }),
    onSuccess: () => {
      showSuccessToast(t("itemHandlers.handlerDeleted"))
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["itemHandlers"] })
    },
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
        className="text-destructive"
      >
        <Trash2 />
        {t("common.delete")}
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("itemHandlers.deleteTitle")}</DialogTitle>
          <DialogDescription>
            {t("itemHandlers.deleteDescription")}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-3">
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              {t("common.cancel")}
            </Button>
          </DialogClose>
          <LoadingButton
            variant="destructive"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
          >
            {t("common.delete")}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default DeleteItemHandler
