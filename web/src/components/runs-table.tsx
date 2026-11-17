"use client";

/** A compact list of runs. Clicking one opens it on its tool's page. */
import Link from "next/link";

import type { Run } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDuration, formatNumber, formatWhen } from "@/lib/format";

import { StatusBadge } from "./ui/badge";
import { Empty } from "./ui/panel";

/** The main inputs in a few words, e.g. "pool cost +2 · everything". */
export function summarizeInputs(inputs: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const value of Object.values(inputs)) {
    if (Array.isArray(value) && value.length) {
      parts.push(String(value[0]) + (value.length > 1 ? ` +${value.length - 1}` : ""));
    } else if (typeof value === "string" && value) {
      parts.push(value);
    }
  }
  return parts.slice(0, 3).join(" · ");
}

export function RunsTable({
  runs,
  showTool = false,
  selectedId,
}: {
  runs: Run[];
  showTool?: boolean;
  selectedId?: string | null;
}) {
  if (!runs.length) return <Empty>No runs yet.</Empty>;
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] text-muted">
          <th className="py-1.5 pr-2 font-semibold">Status</th>
          {showTool && <th className="py-1.5 pr-2 font-semibold">Tool</th>}
          <th className="w-2/5 py-1.5 pr-2 font-semibold">Inputs</th>
          <th className="py-1.5 pr-2 font-semibold">Site</th>
          <th className="py-1.5 pr-2 text-right font-semibold">Rows</th>
          <th className="py-1.5 pr-2 text-right font-semibold">Took</th>
          <th className="py-1.5 text-right font-semibold">When</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.id}
            className={cn("border-b border-border/60 hover:bg-surface", run.id === selectedId && "bg-accent-soft/60")}
          >
            <td className="py-1 pr-2">
              <StatusBadge status={run.status} />
            </td>
            {showTool && <td className="py-1 pr-2 whitespace-nowrap">{run.tool_title}</td>}
            <td className="max-w-0 py-1 pr-2">
              <Link
                href={`/tools/${run.tool_id}?run=${run.id}`}
                className="block truncate text-accent hover:underline"
                title={JSON.stringify(run.inputs)}
              >
                {summarizeInputs(run.inputs) || "Open"}
              </Link>
            </td>
            <td className="py-1 pr-2 text-muted">{run.site}</td>
            <td className="tabular py-1 pr-2 text-right">
              {run.row_count == null ? "" : formatNumber(run.row_count)}
            </td>
            <td className="tabular py-1 pr-2 text-right text-muted">
              {formatDuration(run.started_at, run.finished_at)}
            </td>
            <td className="py-1 text-right whitespace-nowrap text-muted">{formatWhen(run.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
