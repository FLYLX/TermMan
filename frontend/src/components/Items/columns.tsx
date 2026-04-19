import type { ColumnDef } from "@tanstack/react-table"
import { Check, Copy, Users } from "lucide-react"
import { useMemo } from "react"

import type { ItemPublic } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { getStatusLabel } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { ItemActionsMenu } from "./ItemActionsMenu"

type ItemWithExtras = ItemPublic & {
  connected_users?: Record<string, { user_uuid: string; ip: string }>
}

function CopyId({ id }: { id: string }) {
  const [copiedText, copy] = useCopyToClipboard()
  const { t } = useI18n()
  const isCopied = copiedText === id

  return (
    <div className="flex items-center gap-1.5 group">
      <span className="font-mono text-xs text-muted-foreground">{id}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={(event) => {
          event.stopPropagation()
          copy(id)
        }}
      >
        {isCopied ? (
          <Check className="size-3 text-green-500" />
        ) : (
          <Copy className="size-3" />
        )}
        <span className="sr-only">{t("common.copyId")}</span>
      </Button>
    </div>
  )
}

function ItemTitle({ item }: { item: ItemWithExtras }) {
  return <span className="font-medium">{item.title}</span>
}

function ConnectedUsers({ item }: { item: ItemWithExtras }) {
  const connectedUsers = item.connected_users || {}
  const userCount = Object.keys(connectedUsers).length

  return (
    <div className="flex items-center gap-1.5">
      <Users className="size-4 text-muted-foreground" />
      <span
        className={cn(
          "text-sm",
          userCount > 0
            ? "text-green-600 dark:text-green-400"
            : "text-muted-foreground",
        )}
      >
        {userCount}
      </span>
    </div>
  )
}

function StatusBadge({ status }: { status?: string }) {
  const { locale } = useI18n()
  const label = getStatusLabel(locale, status)

  switch (status) {
    case "running":
      return (
        <Badge className="border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400">
          {label}
        </Badge>
      )
    case "starting":
      return (
        <Badge className="border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
          {label}
        </Badge>
      )
    case "stopping":
      return (
        <Badge className="border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400">
          {label}
        </Badge>
      )
    case "stopped":
      return <Badge variant="secondary">{label}</Badge>
    case "error":
      return (
        <Badge className="border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400">
          {label}
        </Badge>
      )
    default:
      return <Badge variant="outline">{label}</Badge>
  }
}

export function useItemColumns() {
  const { t } = useI18n()

  return useMemo<ColumnDef<ItemWithExtras>[]>(
    () => [
      {
        accessorKey: "id",
        header: t("common.id"),
        cell: ({ row }) => <CopyId id={row.original.id} />,
      },
      {
        accessorKey: "title",
        header: t("common.title"),
        cell: ({ row }) => <ItemTitle item={row.original} />,
      },
      {
        accessorKey: "status",
        header: t("common.status"),
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "connected_users",
        header: "Users",
        cell: ({ row }) => <ConnectedUsers item={row.original} />,
      },
      {
        accessorKey: "description",
        header: t("common.description"),
        cell: ({ row }) => {
          const description = row.original.description
          return (
            <span
              className={cn(
                "max-w-xs truncate block text-muted-foreground",
                !description && "italic",
              )}
            >
              {description || t("common.noDescription")}
            </span>
          )
        },
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{t("common.actions")}</span>,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <ItemActionsMenu item={row.original} />
          </div>
        ),
      },
    ],
    [t],
  )
}
