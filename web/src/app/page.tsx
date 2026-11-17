"use client";

import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { RunsTable } from "@/components/runs-table";
import { useCurrentSite } from "@/components/site-context";
import { Badge } from "@/components/ui/badge";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import { useChecks, useRuns, useSite, useSites, useTools } from "@/lib/queries";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="truncate text-[12.5px] font-medium">{children || "—"}</dd>
    </div>
  );
}

function SitePanel({ name }: { name: string | undefined }) {
  const sites = useSites();
  const site = useSite(name);
  const detail = site.data;
  const noSites = sites.data && sites.data.sites.length === 0;
  return (
    <Panel
      title={name ? `Site · ${name}` : "Site"}
      actions={
        name && (
          <Link href={`/sites/${name}`} className="text-[11.5px] text-accent hover:underline">
            Edit site
          </Link>
        )
      }
    >
      {noSites && (
        <Callout>
          There are no sites yet.{" "}
          <Link href="/sites/new" className="font-medium text-accent hover:underline">
            Create your first site
          </Link>{" "}
          so the tools know what they&apos;re working on.
        </Callout>
      )}
      {site.isError && <Callout tone="bad">{site.error.message}</Callout>}
      {detail && (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Fact label="Domain">{detail.domain.replace(/^https?:\/\//, "")}</Fact>
            <Fact label="Central entity">{detail.central_entity}</Fact>
            <Fact label="Entity type">{detail.entity_type}</Fact>
            <Fact label="Market">
              {detail.country.toUpperCase()} · {detail.language}
            </Fact>
          </dl>
          {detail.source_context ? (
            <p className="rounded bg-surface px-3 py-2 text-[12px] leading-relaxed">
              <span className="font-semibold">Source context. </span>
              {detail.source_context.trim()}
            </p>
          ) : (
            <Callout tone="warn">
              No source context in the site file yet: planning tools won't know what the site is for.
            </Callout>
          )}
          {detail.sections.length > 0 && (
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] text-muted">
                  <th className="py-1 font-semibold">Section</th>
                  <th className="py-1 font-semibold">Path</th>
                  <th className="py-1 font-semibold">Role</th>
                </tr>
              </thead>
              <tbody>
                {detail.sections.map((s) => (
                  <tr key={s.path} className="border-b border-border/60">
                    <td className="py-1">{s.name}</td>
                    <td className="py-1 font-mono text-[11.5px] text-muted">{s.path}</td>
                    <td className="py-1">
                      <Badge tone={s.role === "core" ? "accent" : "neutral"}>{s.role}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Panel>
  );
}

export default function OverviewPage() {
  const { site } = useCurrentSite();
  const tools = useTools();
  const runs = useRuns({ limit: 15 });
  const checks = useChecks(site);
  const problems = checks.data?.filter((c) => c.status === "warn" || c.status === "fail") ?? [];

  return (
    <>
      <PageHeader eyebrow="Overview" title="SEO Toolkit" description="Semantic SEO research and planning." />
      {problems.length > 0 && (
        <div className="px-5 pt-4">
          <Callout tone="warn">
            {problems.length === 1 ? problems[0]!.detail : `${problems.length} setup items need attention.`}{" "}
            <Link href="/setup" className="font-medium text-accent hover:underline">
              Open Setup
            </Link>
          </Callout>
        </div>
      )}
      <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <SitePanel name={site} />

        <Panel title="Tools" bodyClassName="p-0">
          {tools.isError && (
            <div className="p-3">
              <Callout tone="bad">{tools.error.message}</Callout>
            </div>
          )}
          <table className="w-full text-[12px]">
            <tbody>
              {tools.data?.map((tool) => (
                <tr key={tool.id} className="border-b border-border/60 last:border-0 hover:bg-surface">
                  <td className="px-3 py-1.5">
                    <Link href={`/tools/${tool.id}`} className="font-medium text-accent hover:underline">
                      {tool.title}
                    </Link>
                    <p className="text-[11.5px] text-muted">{tool.summary}</p>
                  </td>
                  <td className="px-3 py-1.5 text-right align-top">
                    {tool.ready ? (
                      <Badge tone="ok">ready</Badge>
                    ) : (
                      <Badge tone="warn">needs {tool.missing.join(", ")}</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Recent runs" className="xl:col-span-2">
          {runs.isError ? (
            <Callout tone="bad">{runs.error.message}</Callout>
          ) : runs.data ? (
            <RunsTable runs={runs.data} showTool />
          ) : (
            <Empty>Loading…</Empty>
          )}
        </Panel>
      </div>
    </>
  );
}
