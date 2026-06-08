import {
  type ColumnDef,
  type ExpandedState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react"
import React, { useState } from "react"

import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  getSubRows?: (row: TData) => any[]
  subRowsColumns?: ColumnDef<any, any>[]
  onRowClick?: (row: TData) => void
  onSubRowClick?: (row: any) => void
}

export function DataTable<TData, TValue>({
  columns,
  data,
  getSubRows,
  subRowsColumns,
  onRowClick,
  onSubRowClick,
}: DataTableProps<TData, TValue>) {
  const [expanded, setExpanded] = useState<ExpandedState>({})
  const { t } = useI18n()

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSubRows,
    state: {
      expanded,
    },
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
    onExpandedChange: setExpanded,
  })

  return (
    <div className="flex flex-col gap-4">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent">
              {getSubRows && (
                <TableHead key="expand-header" className="w-[40px] p-0">
                  {/* Empty header for expand/collapse button */}
                </TableHead>
              )}
              {headerGroup.headers.map((header) => {
                return (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <React.Fragment key={row.id}>
                <TableRow
                  key={`${row.id}-main`}
                  className={onRowClick ? "cursor-pointer" : undefined}
                  onClick={() => onRowClick?.(row.original)}
                >
                  {getSubRows && (
                    <TableCell className="p-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 p-0"
                        onClick={(event) => {
                          event.stopPropagation()
                          row.toggleExpanded()
                        }}
                      >
                        {row.getIsExpanded() ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                        <span className="sr-only">
                          {row.getIsExpanded()
                            ? t("table.collapse")
                            : t("table.expand")}
                        </span>
                      </Button>
                    </TableCell>
                  )}
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>

                {/* Sub rows */}
                {row.getIsExpanded() &&
                  getSubRows &&
                  subRowsColumns &&
                  (() => {
                    const subRows = getSubRows(row.original)
                    return subRows.length > 0 ? (
                      <TableRow>
                        <TableCell colSpan={columns.length + 1}>
                          <div className="pl-6 pt-1 pb-1">
                            <Table className="w-full">
                              <TableBody>
                                {subRows.map((subRow, index) => (
                                  <TableRow
                                    key={`${row.id}-sub-${index}`}
                                    className={
                                      onSubRowClick
                                        ? "cursor-pointer"
                                        : undefined
                                    }
                                    onClick={() => onSubRowClick?.(subRow)}
                                  >
                                    {subRowsColumns.map((column, colIndex) => (
                                      <TableCell
                                        key={`${row.id}-sub-${index}-${colIndex}`}
                                      >
                                        {typeof column.cell === "function"
                                          ? (column.cell as any)({
                                              row: { original: subRow },
                                            })
                                          : ""}
                                      </TableCell>
                                    ))}
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null
                  })()}
              </React.Fragment>
            ))
          ) : (
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={columns.length + 1}
                className="h-32 text-center text-muted-foreground"
              >
                {t("table.noResults")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {table.getPageCount() > 1 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 border-t bg-muted/20">
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="text-sm text-muted-foreground">
              {t("table.showing", {
                from:
                  table.getState().pagination.pageIndex *
                    table.getState().pagination.pageSize +
                  1,
                to: Math.min(
                  (table.getState().pagination.pageIndex + 1) *
                    table.getState().pagination.pageSize,
                  data.length,
                ),
                total: data.length,
              })}
            </div>
            <div className="flex items-center gap-x-2">
              <p className="text-sm text-muted-foreground">
                {t("table.rowsPerPage")}
              </p>
              <Select
                value={`${table.getState().pagination.pageSize}`}
                onValueChange={(value) => {
                  table.setPageSize(Number(value))
                }}
              >
                <SelectTrigger className="h-8 w-[70px]">
                  <SelectValue
                    placeholder={table.getState().pagination.pageSize}
                  />
                </SelectTrigger>
                <SelectContent side="top">
                  {[5, 10, 25, 50].map((pageSize) => (
                    <SelectItem key={pageSize} value={`${pageSize}`}>
                      {pageSize}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex items-center gap-x-6">
            <div className="flex items-center gap-x-1 text-sm text-muted-foreground">
              <span>{t("table.page")}</span>
              <span className="font-medium text-foreground">
                {table.getState().pagination.pageIndex + 1}
              </span>
              <span>{t("table.of")}</span>
              <span className="font-medium text-foreground">
                {table.getPageCount()}
              </span>
            </div>

            <div className="flex items-center gap-x-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => table.setPageIndex(0)}
                disabled={!table.getCanPreviousPage()}
              >
                <span className="sr-only">{t("table.firstPage")}</span>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                <span className="sr-only">{t("table.previousPage")}</span>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                <span className="sr-only">{t("table.nextPage")}</span>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => table.setPageIndex(table.getPageCount() - 1)}
                disabled={!table.getCanNextPage()}
              >
                <span className="sr-only">{t("table.lastPage")}</span>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
