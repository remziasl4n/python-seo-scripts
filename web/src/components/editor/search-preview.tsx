"use client";

/** The page title, meta description and web address, with a preview of the Google result. */
import { ChevronRight } from "lucide-react";

import type { Draft } from "@/lib/api";
import { cn } from "@/lib/cn";

const TITLE = [30, 60] as const;
const META = [120, 160] as const;

function Counter({ length, range }: { length: number; range: readonly [number, number] }) {
  const ok = length >= range[0] && length <= range[1];
  return (
    <span className={cn("tabular text-[11px]", length === 0 ? "text-muted" : ok ? "text-ok" : "text-warn")}>
      {length} / {range[0]}–{range[1]}
    </span>
  );
}

export function SearchPreview({
  draft,
  domain,
  onChange,
}: {
  draft: Draft;
  domain: string;
  onChange: (changes: Partial<Draft>) => void;
}) {
  const host = domain.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const title = draft.title ?? "";
  const meta = draft.meta_description ?? "";
  const slug = draft.url_slug ?? "";
  const shownTitle = title.length > TITLE[1] ? `${title.slice(0, TITLE[1] - 1)}…` : title;
  const shownMeta = meta.length > META[1] ? `${meta.slice(0, META[1] - 1)}…` : meta;

  return (
    <details open className="group rounded-md border border-border bg-background">
      <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 px-3 text-[12px] font-semibold">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        How it looks in Google
        <span className="ml-auto truncate pl-3 text-[11.5px] font-normal text-muted group-open:hidden">
          {title || "No page title yet"}
        </span>
      </summary>
      <div className="grid gap-4 border-t border-border p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-2.5">
          <label className="block space-y-1">
            <span className="flex items-center justify-between text-[11.5px] font-medium">
              Page title <Counter length={title.length} range={TITLE} />
            </span>
            <input
              value={title}
              onChange={(e) => onChange({ title: e.target.value })}
              placeholder="The blue link in Google"
              className="h-7 w-full rounded border border-border-strong bg-background px-2 text-[12.5px] focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <label className="block space-y-1">
            <span className="flex items-center justify-between text-[11.5px] font-medium">
              Meta description <Counter length={meta.length} range={META} />
            </span>
            <textarea
              value={meta}
              onChange={(e) => onChange({ meta_description: e.target.value })}
              placeholder="The text under the link: what the reader gets from the page"
              rows={3}
              className="w-full resize-none rounded border border-border-strong bg-background px-2 py-1.5 text-[12.5px] leading-snug focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11.5px] font-medium">Web address</span>
            <span className="flex h-7 items-center rounded border border-border-strong bg-background text-[12.5px] focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20">
              <span className="truncate pl-2 text-muted">{host}/</span>
              <input
                value={slug}
                onChange={(e) => onChange({ url_slug: e.target.value.toLowerCase().replace(/\s+/g, "-") })}
                placeholder="page-address"
                className="h-full min-w-0 flex-1 bg-transparent pr-2 focus:outline-none"
              />
            </span>
          </label>
        </div>
        <div className="rounded bg-surface p-3" aria-label="Google preview">
          <p className="truncate text-[12px] text-foreground/80">
            {host} › {slug || "…"}
          </p>
          <p className="mt-0.5 text-[16px] leading-snug text-[#1a0dab] dark:text-[#8ab4f8]">
            {shownTitle || <span className="text-muted">Your page title</span>}
          </p>
          <p className="mt-1 text-[12.5px] leading-snug text-muted">
            {shownMeta || "Your meta description shows here. Without one, Google picks text from the page."}
          </p>
        </div>
      </div>
    </details>
  );
}
