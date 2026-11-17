"use client";

/**
 * A run's results: sortable, filterable, resizable columns, virtualised so thousands of
 * rows stay smooth. Numbers are right-aligned with tabular digits; long text is cut with
 * the full value on hover.
 */
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Download, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { type Column, downloadUrl, type Rows } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCell, formatNumber } from "@/lib/format";

import { Input } from "./ui/field";

type Row = Record<string, unknown>;

function widthFor(column: Column, index: number): number {
  if (column.type === "boolean") return 76;
  if (column.type === "number") return 96;
  return index === 0 ? 200 : 240;
}

export function ResultsTable({ rows, runId }: { rows: Rows; runId: string }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const columns = useMemo<ColumnDef<Row>[]>(
    () =>
      rows.columns.map((column, index) => ({
        id: column.name,
        accessorFn: (row) => row[column.name],
        header: column.name.replace(/_/g, " "),
        size: widthFor(column, index),
        minSize: 50,
        sortDescFirst: column.type === "number",
        meta: { type: column.type },
        cell: (info) => formatCell(info.getValue()),
      })),
    [rows.columns],
  );

  const table = useReactTable({
    data: rows.rows as Row[],
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    globalFilterFn: "includesString",
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const tableRows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 26,
    overscan: 20,
  });
  const totalWidth = table.getTotalSize();

  return (
    <div className="flex flex-col rounded-md border border-border">
      <div className="flex h-10 items-center gap-2 border-b border-border px-2">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute top-1.5 left-2 size-3.5 text-muted" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter rows…"
            className="pl-7"
            aria-label="Filter rows"
          />
        </div>
        <span className="tabular text-[11.5px] text-muted">
          {filter ? `${formatNumber(tableRows.length)} of ` : ""}
          {formatNumber(rows.total)} rows
          {rows.truncated && ` (showing the first ${formatNumber(rows.rows.length)}; download for all)`}
        </span>
        <div className="ml-auto flex gap-1.5">
          {(["csv", "xlsx"] as const).map((format) => (
            <a
              key={format}
              href={downloadUrl(runId, format)}
              className="inline-flex h-7 items-center gap-1.5 rounded border border-border-strong px-2.5 text-[12px] font-medium hover:bg-surface-2"
            >
              <Download className="size-3" /> {format.toUpperCase()}
            </a>
          ))}
        </div>
      </div>

      <div ref={scrollRef} className="max-h-[calc(100vh-320px)] min-h-40 overflow-auto">
        <table className="grid text-[12px]" style={{ width: totalWidth }}>
          <thead className="sticky top-0 z-10 grid bg-surface">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="flex border-b border-border">
                {group.headers.map((header) => {
                  const numeric = header.column.columnDef.meta?.type === "number";
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      style={{ width: header.getSize() }}
                      className="group relative flex h-7 items-center px-2 text-left text-[11px] font-semibold text-muted select-none"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                    >
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "flex w-full items-center gap-1 truncate capitalize hover:text-foreground",
                          numeric && "justify-end",
                          sorted && "text-foreground",
                        )}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === "asc" && <ArrowUp className="size-3 shrink-0" />}
                        {sorted === "desc" && <ArrowDown className="size-3 shrink-0" />}
                      </button>
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        className={cn(
                          "absolute top-0 right-0 h-full w-1 cursor-col-resize opacity-0 group-hover:opacity-100",
                          header.column.getIsResizing() ? "bg-accent opacity-100" : "bg-border-strong",
                        )}
                        aria-hidden
                      />
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="relative grid" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const row = tableRows[item.index]!;
              return (
                <tr
                  key={row.id}
                  data-index={item.index}
                  className="absolute flex w-full border-b border-border/60 hover:bg-surface"
                  style={{ transform: `translateY(${item.start}px)`, height: item.size }}
                >
                  {row.getVisibleCells().map((cell) => {
                    const numeric = cell.column.columnDef.meta?.type === "number";
                    const text = formatCell(cell.getValue());
                    return (
                      <td
                        key={cell.id}
                        style={{ width: cell.column.getSize() }}
                        title={text.length > 30 ? text : undefined}
                        className={cn("flex items-center truncate px-2", numeric && "tabular justify-end")}
                      >
                        <span className="truncate">{text}</span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {tableRows.length === 0 && (
          <p className="py-8 text-center text-[12px] text-muted">
            {filter ? "No rows match the filter." : "This run returned no rows."}
          </p>
        )}
      </div>
    </div>
  );
}

declare module "@tanstack/react-table" {
  interface ColumnMeta<TData, TValue> {
    type?: Column["type"];
  }
}
