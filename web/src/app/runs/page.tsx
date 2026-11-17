"use client";

import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import type { RunStatus } from "@/lib/api";
import { useRuns, useSites, useTools } from "@/lib/queries";

const PAGE = 50;
const STATUSES: RunStatus[] = ["queued", "running", "done", "failed"];

function Filter({ label, value, onChange, children }: { label: string; value: string; onChange: (v: string) => void; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-1.5 text-[11.5px] text-muted">
      {label}
      <Select value={value} onChange={(e) => onChange(e.target.value)} className="w-auto min-w-28" aria-label={label}>
        <option value="">All</option>
        {children}
      </Select>
    </label>
  );
}

export default function RunsPage() {
  const tools = useTools();
  const sites = useSites();
  const [tool, setTool] = useState("");
  const [status, setStatus] = useState("");
  const [site, setSite] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const runs = useRuns({
    tool_id: tool || undefined,
    status: (status || undefined) as RunStatus | undefined,
    site: site || undefined,
    limit,
  });

  function filterBy(setter: (v: string) => void) {
    return (value: string) => {
      setter(value);
      setLimit(PAGE);
    };
  }

  return (
    <>
      <PageHeader eyebrow="Workspace" title="Runs" description="Every tool run, newest first. Click a run to open its results." />
      <div className="p-5">
        <Panel
          bodyClassName="p-0"
          title={
            <span className="flex flex-wrap items-center gap-3 font-normal">
              <Filter label="Tool" value={tool} onChange={filterBy(setTool)}>
                {tools.data?.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </Filter>
              <Filter label="Status" value={status} onChange={filterBy(setStatus)}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Filter>
              <Filter label="Site" value={site} onChange={filterBy(setSite)}>
                {sites.data?.sites.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </Filter>
            </span>
          }
        >
          <div className="px-3 py-1">
            {runs.isError ? (
              <div className="py-2">
                <Callout tone="bad">{runs.error.message}</Callout>
              </div>
            ) : runs.data ? (
              <RunsTable runs={runs.data} showTool />
            ) : (
              <Empty>Loading…</Empty>
            )}
          </div>
          {runs.data && runs.data.length >= limit && (
            <div className="border-t border-border p-2 text-center">
              <Button onClick={() => setLimit(limit + PAGE)} disabled={runs.isFetching}>
                {runs.isFetching ? "Loading…" : "Show more"}
              </Button>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
