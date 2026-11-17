"use client";

import { ChevronRight } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import Markdown from "react-markdown";

import { PageHeader } from "@/components/page-header";
import { RunView } from "@/components/run-view";
import { RunsTable } from "@/components/runs-table";
import { SchemaForm } from "@/components/schema-form";
import { useCurrentSite } from "@/components/site-context";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import { ApiError, type FieldError, type ToolDetail } from "@/lib/api";
import { useRuns, useStartRun, useTool } from "@/lib/queries";

function ToolWorkspace({ tool }: { tool: ToolDetail }) {
  const router = useRouter();
  const runId = useSearchParams().get("run");
  const { site } = useCurrentSite();
  const start = useStartRun();
  const runs = useRuns({ tool_id: tool.id, limit: 10 });
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [startError, setStartError] = useState<string | null>(null);

  function run(inputs: Record<string, unknown>, refresh: boolean) {
    setFieldErrors([]);
    setStartError(null);
    start.mutate(
      { tool_id: tool.id, inputs, site, refresh },
      {
        // Keep the run in the URL, so refreshing or sharing the page shows the same run
        onSuccess: (started) => router.replace(`?run=${started.id}`, { scroll: false }),
        onError: (error) => {
          if (error instanceof ApiError && error.fieldErrors.length) setFieldErrors(error.fieldErrors);
          else setStartError(error.message);
        },
      },
    );
  }

  return (
    <div className="grid gap-4 p-5 lg:grid-cols-[300px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Panel title="Inputs">
          {!tool.ready && (
            <div className="mb-3">
              <Callout tone="warn">
                Needs {tool.missing.join(", ")} in your .env file. Add it, save, and reload this page.
              </Callout>
            </div>
          )}
          <SchemaForm
            key={tool.id}
            schema={tool.input_schema}
            disabled={!tool.ready}
            submitting={start.isPending}
            fieldErrors={fieldErrors}
            onSubmit={run}
          />
          {startError && (
            <div className="mt-3">
              <Callout tone="bad">{startError}</Callout>
            </div>
          )}
        </Panel>

        <details className="group rounded-md border border-border">
          <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 px-3 text-[12px] font-semibold">
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" /> How it works
          </summary>
          <div className="prose-tool border-t border-border px-3 py-2 text-[12px] leading-relaxed">
            <Markdown>{tool.description}</Markdown>
          </div>
        </details>
      </div>

      <div className="min-w-0 space-y-4">
        <Panel title="Results">
          {runId ? (
            <RunView runId={runId} />
          ) : (
            <Empty>Fill in the inputs and press Run. Progress and results appear here.</Empty>
          )}
        </Panel>
        <Panel title="Recent runs of this tool">
          {runs.isError ? (
            <Callout tone="bad">{runs.error.message}</Callout>
          ) : (
            <RunsTable runs={runs.data ?? []} selectedId={runId} />
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function ToolPage() {
  const { group, name } = useParams<{ group: string; name: string }>();
  const tool = useTool(group, name);

  return (
    <>
      <PageHeader
        eyebrow={tool.data?.group_title ?? group}
        title={tool.data?.title ?? "…"}
        description={tool.data?.summary}
      />
      {tool.isError ? (
        <div className="p-5">
          <Callout tone="bad">{tool.error.message}</Callout>
        </div>
      ) : tool.data ? (
        <Suspense>
          <ToolWorkspace tool={tool.data} />
        </Suspense>
      ) : (
        <Empty>Loading…</Empty>
      )}
    </>
  );
}
