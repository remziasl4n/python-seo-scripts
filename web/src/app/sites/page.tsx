"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { useCurrentSite } from "@/components/site-context";
import { Badge } from "@/components/ui/badge";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import { useSites } from "@/lib/queries";

export default function SitesPage() {
  const sites = useSites();
  const { site: current } = useCurrentSite();

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Sites"
        description="The websites tools run against, and what each is about."
        actions={
          <Link
            href="/sites/new"
            className="inline-flex h-7 items-center gap-1.5 rounded bg-accent px-2.5 text-[12px] font-medium text-white hover:opacity-90"
          >
            <Plus className="size-3" /> New site
          </Link>
        }
      />
      <div className="p-5">
        <Panel bodyClassName="p-0">
          {sites.isError ? (
            <div className="p-3">
              <Callout tone="bad">{sites.error.message}</Callout>
            </div>
          ) : !sites.data ? (
            <Empty>Loading…</Empty>
          ) : sites.data.sites.length === 0 ? (
            <Empty>No sites yet. Create one to start running tools.</Empty>
          ) : (
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] text-muted">
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Domain</th>
                  <th className="px-3 py-2 font-semibold">Central entity</th>
                  <th className="px-3 py-2 font-semibold">Market</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {sites.data.sites.map((site) => (
                  <tr key={site.name} className="border-b border-border/60 last:border-0 hover:bg-surface">
                    <td className="px-3 py-1.5">
                      <Link href={`/sites/${site.name}`} className="font-medium text-accent hover:underline">
                        {site.name}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-muted">{site.domain}</td>
                    <td className="px-3 py-1.5">{site.central_entity || <span className="text-muted">—</span>}</td>
                    <td className="px-3 py-1.5 text-muted">
                      {site.country.toUpperCase()} · {site.language}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {site.name === current && <Badge tone="accent">selected</Badge>}{" "}
                      {site.name === sites.data.default && <Badge>default</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </>
  );
}
