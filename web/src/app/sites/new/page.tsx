"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { SiteForm } from "@/components/site-form";
import { useCurrentSite } from "@/components/site-context";
import { Callout } from "@/components/ui/panel";
import { ApiError, type FieldError, type SiteConfig } from "@/lib/api";
import { useSaveSite } from "@/lib/queries";
import { emptySite } from "@/lib/site-form";

export default function NewSitePage() {
  const router = useRouter();
  const { setSite } = useCurrentSite();
  const save = useSaveSite();
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [error, setError] = useState<string | null>(null);

  function create(site: SiteConfig) {
    setFieldErrors([]);
    setError(null);
    save.mutate(site, {
      onSuccess: (created) => {
        setSite(created.name); // start working on the new site straight away
        router.push(`/sites/${created.name}?created=1`);
      },
      onError: (e) => {
        if (e instanceof ApiError && e.fieldErrors.length) setFieldErrors(e.fieldErrors);
        else setError(e.message);
      },
    });
  }

  return (
    <>
      <PageHeader eyebrow="Sites" title="New site" description="Tell the tools about a website: what it is, who it's for, and how it's organised." />
      <div className="space-y-3 p-5">
        {error && <Callout tone="bad">{error}</Callout>}
        {fieldErrors.length > 0 && <Callout tone="bad">Some fields need fixing: see the messages below.</Callout>}
        <SiteForm
          initial={emptySite()}
          isNew
          saving={save.isPending}
          fieldErrors={fieldErrors}
          onSubmit={create}
          extraActions={
            <Link href="/sites" className="text-[12px] text-muted hover:text-foreground">
              Cancel
            </Link>
          }
        />
      </div>
    </>
  );
}
