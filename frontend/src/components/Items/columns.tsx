import { Link } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { Check, Copy, Users } from "lucide-react"

import type { ItemPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
import { ItemActionsMenu } from "./ItemActionsMenu"

type ItemWithExtras = ItemPublic & {
  connected_users?: Record<string, { user_uuid: string; ip: string }>;
}

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

function ItemTitleLink({ item }: { item: ItemWithExtras }) {
  return (
    <Button asChild variant="link" className="h-auto p-0 text-left">
      <Link to="/items/$itemId" params={{ itemId: item.id }}>
        {item.title}
      </Link>
    </Button>
  )
}

function ConnectedUsers({ item }: { item: ItemWithExtras }) {
  const connectedUsers = item.connected_users || {}
  const userCount = Object.keys(connectedUsers).length
  
  return (
    <div className="flex items-center gap-1.5">
      <Users className="size-4 text-muted-foreground" />
      <span className={cn(
        "text-sm",
        userCount > 0 ? "text-green-600 dark:text-green-400" : "text-muted-foreground"
      )}>
        {userCount}
      </span>
    </div>
  )
}

function StatusBadge({ status }: { status?: string }) {
  switch (status) {
    case "running":
      return (
        <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
          Running
        </Badge>
      )
    case "starting":
      return (
        <Badge className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
          Starting
        </Badge>
      )
    case "stopping":
      return (
        <Badge className="border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400">
          Stopping
        </Badge>
      )
    case "stopped":
      return (
        <Badge variant="secondary">Stopped</Badge>
      )
    case "error":
      return (
        <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
          Error
        </Badge>
      )
    default:
      return <Badge variant="outline">Unknown</Badge>
  }
}

export const columns: ColumnDef<ItemWithExtras>[] = [
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => <CopyId id={row.original.id} />,
  },
  {
    accessorKey: "title",
    header: "Title",
    cell: ({ row }) => <ItemTitleLink item={row.original} />,
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  },
  {
    accessorKey: "connected_users",
    header: "Users",
    cell: ({ row }) => <ConnectedUsers item={row.original} />,
  },
  {
    accessorKey: "description",
    header: "Description",
    cell: ({ row }) => {
      const description = row.original.description
      return (
        <span
          className={cn(
            "max-w-xs truncate block text-muted-foreground",
            !description && "italic",
          )}
        >
          {description || "No description"}
        </span>
      )
    },
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <ItemActionsMenu item={row.original} />
      </div>
    ),
  },
]
