import type { ColumnDef } from "@tanstack/react-table"
import { Check, Copy } from "lucide-react"

import type { ItemHandlerPublic } from "@/client"
import { ItemHandlerAssociationsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useQuery } from "@tanstack/react-query"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
import AddItemToHandler from "./AddItemToHandler"
import { ItemHandlerActionsMenu } from "./ItemHandlerActionsMenu"

function CopyId({ id }: { id: string }) {
  const [copiedText, copy] = useCopyToClipboard()
  const isCopied = copiedText === id

  return (
    <div className="flex items-center gap-1.5 group">
      <span className="font-mono text-xs text-muted-foreground">{id}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={() => copy(id)}
      >
        {isCopied ? (
          <Check className="size-3 text-green-500" />
        ) : (
          <Copy className="size-3" />
        )}
        <span className="sr-only">Copy ID</span>
      </Button>
    </div>
  )
}

function ItemCount({ itemHandlerId }: { itemHandlerId: string }) {
  // Only fetch items if itemHandlerId is valid
  const { data: items, isLoading } = useQuery({
    queryFn: () => ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: [`itemHandler-${itemHandlerId}-items-count`],
    enabled: !!itemHandlerId, // Only run query if itemHandlerId is truthy
  });

  const count = items?.length || 0;

  return (
    <Badge variant="secondary" className="ml-2">
      {isLoading ? "..." : count}
    </Badge>
  );
}

export const itemColumns: ColumnDef<any>[] = [
  {
    id: "title",
    accessorKey: "title",
    header: "Item Title",
    cell: ({ row }) => (
      <span className="font-medium">{row.original.title || "Untitled"}</span>
    ),
  },
  {
    id: "description",
    accessorKey: "description",
    header: "Description",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {row.original.description || "No description"}
      </span>
    ),
  },
  {
    id: "status",
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {row.original.status || "Unknown"}
      </span>
    ),
  },
];

export const columns: ColumnDef<ItemHandlerPublic>[] = [
  {
    id: "id",
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => <CopyId id={row.original.id} />,
  },
  {
    id: "name",
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => (
      <div className="flex items-center">
        <span className="font-medium">{row.original.name}</span>
        <ItemCount itemHandlerId={row.original.id} />
      </div>
    ),
  },
  {
    id: "model",
    accessorKey: "model",
    header: "Model",
    cell: ({ row }) => {
      const model = row.original.model
      return (
        <span
          className={cn(
            "max-w-xs truncate block text-muted-foreground",
            !model && "italic",
          )}
        >
          {model || "No model"}
        </span>
      )
    },
  },
  {
    id: "api_key",
    accessorKey: "api_key",
    header: "API Key",
    cell: ({ row }) => {
      const apiKey = row.original.api_key
      return (
        <span
          className={cn(
            "max-w-xs truncate block text-muted-foreground",
            !apiKey && "italic",
          )}
        >
          {apiKey ? `****${apiKey.slice(-4)}` : "No API key"}
        </span>
      )
    },
  },
  {
    id: "api_url",
    accessorKey: "api_url",
    header: "API URL",
    cell: ({ row }) => {
      const apiUrl = row.original.api_url
      return (
        <span
          className={cn(
            "max-w-xs truncate block text-muted-foreground",
            !apiUrl && "italic",
          )}
        >
          {apiUrl || "No API URL"}
        </span>
      )
    },
  },
  {
    id: "add-item",
    header: () => <span className="sr-only">Add Item</span>,
    cell: ({ row }) => (
      <AddItemToHandler itemHandlerId={row.original.id} />
    ),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <ItemHandlerActionsMenu itemHandler={row.original} />
      </div>
    ),
  },
]
