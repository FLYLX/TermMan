import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { ItemHandlerPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import DeleteItemHandler from "./DeleteItemHandler"
import EditItemHandler from "./EditItemHandler"

interface ItemHandlerActionsMenuProps {
  itemHandler: ItemHandlerPublic
}

export const ItemHandlerActionsMenu = ({
  itemHandler,
}: ItemHandlerActionsMenuProps) => {
  const [open, setOpen] = useState(false)

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditItemHandler
          itemHandler={itemHandler}
          onSuccess={() => setOpen(false)}
        />
        <DeleteItemHandler
          id={itemHandler.id}
          onSuccess={() => setOpen(false)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
