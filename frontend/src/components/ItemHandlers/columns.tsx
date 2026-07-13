import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useMemo } from "react"
import type { ItemHandlerPublic } from "@/client"
import { ItemHandlerAssociationsService } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { SecretValue } from "@/components/ui/secret-value"
import { cn } from "@/lib/utils"
import { ItemHandlerActionsMenu } from "./ItemHandlerActionsMenu"

function ItemCount({ itemHandlerId }: { itemHandlerId: string }) {
  // Only fetch items if itemHandlerId is valid
  const { data: items, isLoading } = useQuery({
    queryFn: () =>
      ItemHandlerAssociationsService.getItemsForHandler({ itemHandlerId }),
    queryKey: [`itemHandler-${itemHandlerId}-items-count`],
    enabled: !!itemHandlerId, // Only run query if itemHandlerId is truthy
  })

  const count = items?.length || 0

  return (
    <Badge variant="secondary" className="ml-2">
      {isLoading ? "..." : count}
    </Badge>
  )
}

export function useItemHandlerSubColumns() {
  const { t } = useI18n()

  return useMemo<ColumnDef<any>[]>(
    () => [
      {
        id: "title",
        accessorKey: "title",
        header: t("itemHandlers.itemTitle"),
        cell: ({ row }) => (
          <span className="font-medium">
            {row.original.title || t("common.untitled")}
          </span>
        ),
      },
      {
        id: "description",
        accessorKey: "description",
        header: t("common.description"),
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.description || t("common.noDescription")}
          </span>
        ),
      },
      {
        id: "status",
        accessorKey: "status",
        header: t("common.status"),
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.status || t("common.unknown")}
          </span>
        ),
      },
    ],
    [t],
  )
}

export function useItemHandlerColumns() {
  const { t } = useI18n()

  return useMemo<ColumnDef<ItemHandlerPublic>[]>(
    () => [
      {
        id: "name",
        accessorKey: "name",
        header: t("common.name"),
        cell: ({ row }) => (
          <div className="flex items-center">
            <span className="font-medium">{row.original.name}</span>
            <ItemCount itemHandlerId={row.original.id} />
            <Badge variant="outline" className="ml-2">
              {
                (
                  ((row.original as any).enabled_knowledge_files ??
                    []) as string[]
                ).length
              }{" "}
              {t("itemHandlers.detail.knowledge")}
            </Badge>
          </div>
        ),
      },
      {
        id: "model",
        accessorKey: "model",
        header: t("common.model"),
        cell: ({ row }) => {
          const model = row.original.model
          return (
            <span
              className={cn(
                "max-w-xs truncate block text-muted-foreground",
                !model && "italic",
              )}
            >
              {model || t("common.noModel")}
            </span>
          )
        },
      },
      {
        id: "api_key",
        accessorKey: "api_key",
        header: t("common.apiKey"),
        cell: ({ row }) => {
          const apiKey = row.original.api_key
          return (
            <SecretValue
              value={apiKey}
              label={t("common.apiKey")}
              emptyText={t("common.noApiKey")}
              compact
            />
          )
        },
      },
      {
        id: "api_url",
        accessorKey: "api_url",
        header: t("common.apiUrl"),
        cell: ({ row }) => {
          const apiUrl = row.original.api_url
          return (
            <span
              className={cn(
                "max-w-xs truncate block text-muted-foreground",
                !apiUrl && "italic",
              )}
            >
              {apiUrl || t("common.noApiUrl")}
            </span>
          )
        },
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{t("common.actions")}</span>,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <ItemHandlerActionsMenu itemHandler={row.original} />
          </div>
        ),
      },
    ],
    [t],
  )
}
