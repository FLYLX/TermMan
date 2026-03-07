import type { ColumnDef } from "@tanstack/react-table"
import { Check, Copy } from "lucide-react"

import type { ItemHandlerPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
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

export const columns: ColumnDef<ItemHandlerPublic>[] = [
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => <CopyId id={row.original.id} />,
  },
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => (
      <span className="font-medium">{row.original.name}</span>
    ),
  },
  {
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
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <ItemHandlerActionsMenu itemHandler={row.original} />
      </div>
    ),
  },
]
