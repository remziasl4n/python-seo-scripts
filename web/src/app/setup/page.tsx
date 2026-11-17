"use client";

import { LoaderCircle, Plug } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { useCurrentSite } from "@/components/site-context";
import { CheckBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import type { Check } from "@/lib/api";
import { useChecks, useLiveChecks } from "@/lib/queries";

function ChecksTable({ checks }: { checks: Check[] }) {
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] text-muted">
          <th className="w-20 py-1.5 pr-2 font-semibold">Status</th>
          <th className="w-24 py-1.5 pr-2 font-semibold">Area</th>
          <th className="w-56 py-1.5 pr-2 font-semibold">Check</th>
          <th className="py-1.5 font-semibold">Detail</th>
        </tr>
      </thead>
      <tbody>
        {checks.map((check) => (
          <tr key={`${check.area}-${check.name}`} className="border-b border-border/60 align-top last:border-0">
            <td className="py-1.5 pr-2">
              <CheckBadge status={check.status} />
            </td>
            <td className="py-1.5 pr-2 text-muted">{check.area}</td>
            <td className="py-1.5 pr-2 font-medium">{check.name}</td>
            <td className="py-1.5 whitespace-pre-line text-muted">{check.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SetupPage() {
  const { site } = useCurrentSite();
  const checks = useChecks(site);
  const live = useLiveChecks();

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Setup"
        description="What's configured, and what each key unlocks. Keys live in the .env file in the project folder."
      />
      <div className="space-y-4 p-5">
        <Panel title="Configuration" bodyClassName="px-3 py-1">
          {checks.isError ? (
            <div className="py-2">
              <Callout tone="bad">{checks.error.message}</Callout>
            </div>
          ) : checks.data ? (
            <ChecksTable checks={checks.data} />
          ) : (
            <Empty>Loading…</Empty>
          )}
        </Panel>

        <Panel
          title="Live connection test"
          actions={
            <Button variant="primary" onClick={() => live.mutate()} disabled={live.isPending}>
              {live.isPending ? <LoaderCircle className="size-3 animate-spin" /> : <Plug className="size-3" />}
              {live.isPending ? "Testing…" : "Test connections"}
            </Button>
          }
        >
          <p className="mb-2 text-[11.5px] text-muted">
            Makes one small real call to each configured API: one Gemini reply, one embedding, one grounded
            search and one autocomplete request. Each gets one try of up to 30 seconds.
          </p>
          {live.isError && <Callout tone="bad">{live.error.message}</Callout>}
          {live.data && <ChecksTable checks={live.data} />}
        </Panel>
      </div>
    </>
  );
}
