"use client";

/**
 * A run's written report (e.g. a content plan), as a readable document. Checkboxes can be
 * ticked while you work (not saved); Copy and Download take the Markdown into a doc.
 */
import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "./ui/button";

export function ReportView({ markdown, downloadHref }: { markdown: string; downloadHref: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="rounded-md border border-border">
      <div className="flex h-10 items-center justify-end gap-1.5 border-b border-border px-2">
        <span className="mr-auto pl-1 text-[11.5px] text-muted">
          Copy it into Google Docs or Notion, or send it to your writer.
        </span>
        <Button onClick={copy}>
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />} {copied ? "Copied" : "Copy"}
        </Button>
        <a
          href={downloadHref}
          className="inline-flex h-7 items-center gap-1.5 rounded border border-border-strong px-2.5 text-[12px] font-medium hover:bg-surface-2"
        >
          <Download className="size-3" /> Download (.md)
        </a>
      </div>
      <article className="prose-plan max-h-[calc(100vh-300px)] overflow-y-auto px-5 py-4">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Let people tick items off while they work through the plan
            input: ({ checked, type }) =>
              type === "checkbox" ? <input type="checkbox" defaultChecked={checked} className="mr-1.5 size-3.5 accent-[var(--accent)]" /> : null,
          }}
        >
          {markdown}
        </Markdown>
      </article>
    </div>
  );
}
