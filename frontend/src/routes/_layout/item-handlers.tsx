import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { Suspense, useEffect, useState } from "react"

import {
  type Item,
  ItemHandlerAssociationsService,
  ItemHandlersService,
} from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import AddItemHandler from "@/components/ItemHandlers/AddItemHandler"
import { columns, itemColumns } from "@/components/ItemHandlers/columns"
import PendingItems from "@/components/Pending/PendingItems"

function getItemHandlersQueryOptions() {
  return {
    queryFn: async () => {
      // Get all item handlers
      const itemHandlers = await ItemHandlersService.readItemHandlers({
        skip: 0,
        limit: 100,
      })

      // For each item handler, get its associated items and attach them
      // Only process handlers with a valid id
      const itemHandlersWithItems = await Promise.all(
        itemHandlers.map(async (handler) => {
          // Initialize _items as an empty array by default
          let items: Item[] = []

          // Only fetch items if handler has a valid id
          if (handler.id) {
            try {
              items = await ItemHandlerAssociationsService.getItemsForHandler({
                itemHandlerId: handler.id,
              })
            } catch (error) {
              console.error(
                `Failed to fetch items for handler ${handler.id}:`,
                error,
              )
            }
          }

          return {
            ...handler,
            _items: items,
          }
        }),
      )

      return itemHandlersWithItems
    },
    queryKey: ["itemHandlers"],
    staleTime: 0, // Data is always stale, so it will refetch when component mounts
    cacheTime: 30000, // Cache data for 30 seconds
  }
}

export const Route = createFileRoute("/_layout/item-handlers")({
  component: ItemHandlers,
  head: () => ({
    meta: [
      {
        title: "Item Handlers - FastAPI Template",
      },
    ],
  }),
})

function ItemHandlersTableContent() {
  const { data: initialItemHandlers } = useSuspenseQuery(
    getItemHandlersQueryOptions(),
  )
  const [itemHandlers, setItemHandlers] = useState<any[]>(
    initialItemHandlers || [],
  )

  useEffect(() => {
    // Function to fetch items for each item handler and update state
    const fetchItemsForHandlers = async () => {
      if (!initialItemHandlers) return

      // Always fetch items for each handler to ensure we have the latest data
      // Only process handlers with a valid id
      const handlersWithItems = await Promise.all(
        initialItemHandlers.map(async (handler) => {
          // Initialize _items as an empty array by default
          let items: Item[] = []

          // Only fetch items if handler has a valid id
          if (handler.id) {
            try {
              items = await ItemHandlerAssociationsService.getItemsForHandler({
                itemHandlerId: handler.id,
              })
            } catch (error) {
              console.error(
                `Failed to fetch items for handler ${handler.id}:`,
                error,
              )
            }
          }

          return {
            ...handler,
            _items: items,
          }
        }),
      )

      setItemHandlers(handlersWithItems)
    }

    fetchItemsForHandlers()
  }, [initialItemHandlers])

  // Use initialItemHandlers.length for the empty state check to avoid showing empty message during async fetch
  if (initialItemHandlers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-12">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">
          You don't have any item handlers yet
        </h3>
        <p className="text-muted-foreground">
          Add a new item handler to get started
        </p>
      </div>
    )
  }

  // Function to get sub rows (items) for each item handler
  const getSubRows = (row: any) => row._items || []

  return (
    <DataTable
      columns={columns}
      data={itemHandlers}
      getSubRows={getSubRows}
      subRowsColumns={itemColumns}
    />
  )
}

function ItemHandlersTable() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemHandlersTableContent />
    </Suspense>
  )
}

function ItemHandlers() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Item Handlers</h1>
          <p className="text-muted-foreground">
            Create and manage your item handlers
          </p>
        </div>
        <AddItemHandler />
      </div>
      <ItemHandlersTable />
    </div>
  )
}
