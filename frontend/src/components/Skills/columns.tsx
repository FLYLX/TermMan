import type { ColumnDef } from "@tanstack/react-table"
import type { SkillListItem } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import DeleteSkill from "./DeleteSkill"
import EditSkill from "./EditSkill"
import { SkillDetailDialog } from "./SkillDetailDialog"

export const columns: ColumnDef<SkillListItem>[] = [
  {
    accessorKey: "skill_id",
    header: "ID",
    cell: ({ row }) => (
      <code className="text-sm bg-muted px-2 py-1 rounded">
        {row.getValue("skill_id")}
      </code>
    ),
  },
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => (
      <SkillDetailDialog skill={row.original}>
        <Button variant="link" className="p-0 h-auto font-medium">
          {row.getValue("name")}
        </Button>
      </SkillDetailDialog>
    ),
  },
  {
    accessorKey: "description",
    header: "Description",
    cell: ({ row }) => {
      const desc = row.getValue("description") as string
      return (
        <span className="text-muted-foreground text-sm truncate max-w-[300px] block">
          {desc || "-"}
        </span>
      )
    },
  },
  {
    accessorKey: "category",
    header: "Category",
    cell: ({ row }) => (
      <Badge variant="secondary">{row.getValue("category")}</Badge>
    ),
  },
  {
    id: "actions",
    header: "Actions",
    cell: ({ row }) => {
      return (
        <div className="flex items-center gap-1">
          <EditSkill skill={row.original} />
          <DeleteSkill skill={row.original} />
        </div>
      )
    },
  },
]
