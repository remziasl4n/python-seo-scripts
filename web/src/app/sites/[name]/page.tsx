"use client";

import { Download, Trash2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { SiteForm } from "@/components/site-form";
import { Button } from "@/components/ui/button";
import { Callout, Empty } from "@/components/ui/panel";
import { ApiError, type FieldError, type SiteConfig } from "@/lib/api";
import { useDeleteSite, useSaveSite, useSite } from "@/lib/queries";
import { toFormState } from "@/lib/site-form";

function DeleteButton({ name }: { name: string }) {
  const router = useRouter();
  const remove = useDeleteSite();
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <Button type="button" variant="ghost" className="ml-auto text-bad hover:text-bad" onClick={() => setConfirming(true)}>
        <Trash2 className="size-3" /> Delete site
      </Button>
    );
  }
  return (
    <span className="ml-auto flex items-center gap-2 text-[12px]">
      Delete {name}? Its past runs stay in the history.
      <Button
        type="button"
        className="border-bad text-bad"
        disabled={remove.isPending}
        onClick={() => remove.mutate(name, { onSuccess: () => router.push("/sites") })}
      >
        Yes, delete
      </Button>
      <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>
        Keep it
      </Button>
      {remove.isError && <span className="text-bad">{remove.error.message}</span>}
    </span>
  );
}

function EditSite({ name }: { name: string }) {
  const site = useSite(name);
  const save = useSaveSite(name);
  const created = useSearchParams().get("created") === "1";
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function update(next: SiteConfig) {
    setFieldErrors([]);
    setError(null);
    setSaved(false);
    save.mutate(next, {
      onSuccess: () => setSaved(true),
      onError: (e) => {
        if (e instanceof ApiError && e.fieldErrors.length) setFieldErrors(e.fieldErrors);
        else setError(e.message);
      },
    });
  }

  if (site.isError) return <Callout tone="bad">{site.error.message}</Callout>;
  if (!site.data) return <Empty>Loading…</Empty>;

  return (
    <div className="space-y-3">
      {created && !saved && <Callout>Site created and selected. Tools now run against it.</Callout>}
      {saved && <Callout>Saved.</Callout>}
      {error && <Callout tone="bad">{error}</Callout>}
      {fieldErrors.length > 0 && <Callout tone="bad">Some fields need fixing: see the messages below.</Callout>}
      <SiteForm
        key={site.dataUpdatedAt}
        initial={toFormState(site.data)}
        isNew={false}
        saving={save.isPending}
        fieldErrors={fieldErrors}
        onSubmit={update}
        extraActions={
          <>
            <a
              href={`/api/sites/${encodeURIComponent(name)}/export`}
              className="inline-flex h-7 items-center gap-1.5 rounded border border-border-strong px-2.5 text-[12px] font-medium hover:bg-surface-2"
            >
              <Download className="size-3" /> Export YAML
            </a>
            <DeleteButton name={name} />
          </>
        }
      />
    </div>
  );
}

export default function SitePage() {
  const { name } = useParams<{ name: string }>();
  return (
    <>
      <PageHeader eyebrow="Sites" title={name} description="Everything tools know about this website." />
      <div className="p-5">
        <Suspense>
          <EditSite name={name} />
        </Suspense>
      </div>
    </>
  );
}
