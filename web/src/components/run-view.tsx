"use client";

/** One run: live status and progress while it runs, then metrics, notes and the results. */
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { formatDuration, formatNumber, formatWhen } from "@/lib/format";
import { isActive, useRun, useRunRows } from "@/lib/queries";

import { ResultsTable } from "./results-table";
import { StatusBadge } from "./ui/badge";
import { Callout, ProgressBar } from "./ui/panel";

/** Re-render every second while `active`, so elapsed times count up. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

export function RunView({ runId }: { runId: string }) {
  const run = useRun(runId);
  const rows = useRunRows(run.data);
  const active = isActive(run.data);
  const now = useNow(active);

  if (run.isPending) {
    return <p className="flex items-center gap-2 text-[12px] text-muted"><LoaderCircle className="size-3.5 animate-spin" /> Loading run…</p>;
  }
  if (run.isError) return <Callout tone="bad">{run.error.message}</Callout>;

  const r = run.data;
  const duration = formatDuration(r.started_at, r.finished_at, now);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
        <StatusBadge status={r.status} />
        <span className="text-muted">
          Started {formatWhen(r.created_at, now)}
          {duration && ` · ${duration}`} · site <span className="text-foreground">{r.site}</span>
          {r.refresh && " · cache ignored"}
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted">{r.id}</span>
      </div>

      {active && (
        <div className="space-y-1.5 rounded-md border border-border bg-surface p-3">
          <div className="flex items-center justify-between text-[12px]">
            <span className="flex items-center gap-2">
              <LoaderCircle className="size-3.5 animate-spin text-accent" />
              {r.message || "Working…"}
            </span>
            <span className="tabular text-muted">{Math.round(r.progress * 100)}%</span>
          </div>
          <ProgressBar value={r.progress} />
        </div>
      )}

      {r.status === "failed" && r.error && <Callout tone="bad">{r.error}</Callout>}

      {Object.keys(r.metrics).length > 0 && (
        <dl className="flex flex-wrap overflow-hidden rounded-md border border-border">
          {Object.entries(r.metrics).map(([label, value]) => (
            <div key={label} className="min-w-[130px] border-r border-border px-3 py-2 last:border-r-0">
              <dt className="text-[11px] text-muted">{label}</dt>
              <dd className="tabular text-[17px] font-semibold">
                {typeof value === "number" ? formatNumber(value) : value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {r.notes.map((note) => (
        <Callout key={note}>{note}</Callout>
      ))}

      {r.status === "done" &&
        (rows.isPending ? (
          <p className="text-[12px] text-muted">Loading results…</p>
        ) : rows.isError ? (
          <Callout tone="bad">{rows.error.message}</Callout>
        ) : (
          <ResultsTable rows={rows.data} runId={r.id} />
        ))}
    </div>
  );
}
