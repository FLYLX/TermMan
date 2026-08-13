import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { ItemHandlersService } from "@/client"
import AddItemHandler from "@/components/ItemHandlers/AddItemHandler"

export const Route = createFileRoute("/_layout/item-handlers/")({
  component: ItemHandlersIndex,
})

function ItemHandlersIndex() {
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const handlers = (await ItemHandlersService.readItemHandlers({
          skip: 0,
          limit: 1,
        })) as any
        const first = Array.isArray(handlers)
          ? handlers[0]
          : (handlers?.data ?? [])[0]
        if (!cancelled && first?.id) {
          await navigate({
            to: "/item-handlers/$itemHandlerId",
            params: { itemHandlerId: String(first.id) },
            replace: true,
          })
        }
      } catch {
        // stay on empty state
      }
    })()
    return () => {
      cancelled = true
    }
  }, [navigate])

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24">
      <p className="text-sm text-muted-foreground">
        还没有调度器，先创建一个。
      </p>
      <AddItemHandler />
    </div>
  )
}
