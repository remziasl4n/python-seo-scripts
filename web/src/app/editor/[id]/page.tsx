"use client";

/**
 * The content editor: the draft on the left, the score and what to do next on the right.
 * Saves on its own after a pause in typing, and rescores after a shorter one.
 */
import type { Editor } from "@tiptap/react";
import { ArrowLeft, Check, Copy, Download, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  addSection,
  DraftEditor,
  goToHeading,
  highlightTerm,
  refreshHints,
  setMainHeading,
  Toolbar,
  useDraftEditor,
} from "@/components/editor/rich-editor";
import { ScorePanel } from "@/components/editor/score-panel";
import { SearchPreview } from "@/components/editor/search-preview";
import { Button } from "@/components/ui/button";
import { Callout, Empty } from "@/components/ui/panel";
import type { DocumentRecord, Draft } from "@/lib/api";
import { fingerprint, isEmptyHtml, outlineHtml } from "@/lib/editor";
import {
  useBrief,
  useCheckAnswers,
  useDocument,
  useRebuildBrief,
  useSaveDocument,
  useScore,
  useSite,
} from "@/lib/queries";
import { useDebounced } from "@/lib/use-debounced";

const SCORE_AFTER_MS = 450;
const SAVE_AFTER_MS = 1200;

function draftOf(doc: DocumentRecord): Draft {
  return {
    name: doc.name,
    title: doc.title,
    meta_description: doc.meta_description,
    url_slug: doc.url_slug,
    content: doc.content,
  };
}

async function copyRich(editor: Editor) {
  const html = editor.getHTML();
  const text = editor.getText({ blockSeparator: "\n\n" });
  if (typeof ClipboardItem !== "undefined") {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      }),
    ]);
  } else {
    await navigator.clipboard.writeText(text);
  }
}

function Workspace({ doc }: { doc: DocumentRecord }) {
  const site = useSite(doc.site);
  const briefState = useBrief(doc.id);
  const brief = briefState.data?.brief ?? null;
  const save = useSaveDocument(doc.id);
  const check = useCheckAnswers(doc.id);
  const rebuild = useRebuildBrief(doc.id);

  const [draft, setDraft] = useState<Draft>(() => draftOf(doc));
  const [checkedAt, setCheckedAt] = useState(doc.answers_checked_at);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const lastSaved = useRef(fingerprint(draftOf(doc)));

  // What to write under each of the brief's questions, shown in empty sections
  const hints = useMemo(
    () => new Map((brief?.questions ?? []).map((q) => [q.heading.trim().toLowerCase(), q.what_to_say])),
    [brief],
  );
  const editor = useDraftEditor(
    doc.content,
    (html) => setDraft((d) => ({ ...d, content: html })),
    (heading) => hints.get(heading.trim().toLowerCase()) || undefined,
  );
  useEffect(() => {
    if (editor) refreshHints(editor);
  }, [editor, hints]);

  // Once the brief is ready, fill in an empty title, description and address from it
  const filled = useRef(false);
  useEffect(() => {
    if (!brief || filled.current) return;
    filled.current = true;
    setDraft((d) => ({
      ...d,
      title: d.title || brief.title,
      meta_description: d.meta_description || brief.meta_description,
      url_slug: d.url_slug || brief.url_slug,
    }));
  }, [brief]);

  // Score after a short pause in typing
  const settled = useDebounced(draft, SCORE_AFTER_MS);
  const version = useMemo(() => fingerprint(settled), [settled]);
  const score = useScore(doc.id, settled, version, Boolean(brief));

  // Save after a longer pause
  const toSave = useDebounced(draft, SAVE_AFTER_MS);
  const { mutate: saveDraft } = save;
  useEffect(() => {
    const print = fingerprint(toSave);
    if (print === lastSaved.current || !toSave.name.trim()) return;
    saveDraft(toSave, { onSuccess: () => (lastSaved.current = print) });
  }, [toSave, saveDraft]);

  // Don't lose the last few seconds of typing when leaving the page
  const latest = useRef(draft);
  latest.current = draft;
  const dirty = fingerprint(draft) !== lastSaved.current;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(
    () => () => {
      if (fingerprint(latest.current) === lastSaved.current) return;
      void fetch(`/api/documents/${encodeURIComponent(doc.id)}`, {
        method: "PUT",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(latest.current),
      });
    },
    [doc.id],
  );

  function change(changes: Partial<Draft>) {
    setDraft((d) => ({ ...d, ...changes }));
  }

  function checkAnswers() {
    const current = draft;
    check.mutate(current, {
      onSuccess: (saved) => {
        lastSaved.current = fingerprint(current);
        setCheckedAt(saved.answers_checked_at);
      },
    });
  }

  async function download() {
    if (dirty) {
      await save.mutateAsync(draft);
      lastSaved.current = fingerprint(draft);
    }
    window.location.href = `/api/documents/${encodeURIComponent(doc.id)}/export`;
  }

  const status = save.isPending
    ? "Saving…"
    : save.isError
      ? `Not saved: ${save.error.message}`
      : dirty
        ? "Unsaved changes"
        : "Saved";
  const domain = site.data?.domain ?? "https://www.example.com/";

  return (
    <div className="flex flex-col lg:h-full">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
        <Link href="/editor" className="inline-flex items-center gap-1 text-[12px] text-muted hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Drafts
        </Link>
        <span className="text-border" aria-hidden>
          /
        </span>
        <input
          value={draft.name}
          onChange={(e) => change({ name: e.target.value })}
          aria-label="Draft name"
          className="min-w-0 flex-1 truncate rounded bg-transparent px-1 text-[13px] font-semibold hover:bg-surface-2 focus:bg-surface-2 focus:outline-none"
        />
        <span className="hidden truncate text-[11.5px] text-muted md:inline">
          “{doc.keyword}” · {doc.site}
        </span>
        <span
          className={`hidden text-[11.5px] sm:inline ${save.isError ? "text-bad" : "text-muted"}`}
          role="status"
          aria-live="polite"
        >
          {status}
        </span>
        <Button
          onClick={async () => {
            if (!editor) return;
            await copyRich(editor);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
          title="Copy with formatting, for Google Docs, WordPress or email"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />} {copied ? "Copied" : "Copy"}
        </Button>
        <Button onClick={download} title="Download as a web page (.html)">
          <Download className="size-3" /> Download
        </Button>
      </header>

      <div className="grid lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="bg-surface lg:min-h-0 lg:overflow-y-auto">
          <div className="mx-auto max-w-[860px] space-y-3 p-4 lg:p-6">
            <SearchPreview draft={draft} domain={domain} onChange={change} />
            <article className="rounded-md border border-border bg-background shadow-sm">
              <Toolbar editor={editor} />
              <div className="px-6 py-6 lg:px-12 lg:py-10">
                <DraftEditor editor={editor} />
              </div>
            </article>
          </div>
        </div>
        <aside className="border-t border-border bg-background lg:min-h-0 lg:overflow-y-auto lg:border-t-0 lg:border-l">
          <ScorePanel
            score={score.data}
            scoring={score.isFetching}
            briefState={briefState.data}
            highlighted={highlighted}
            onHighlight={(term) => {
              setHighlighted(term);
              if (editor) highlightTerm(editor, term);
            }}
            onGoTo={(heading) => editor && goToHeading(editor, heading)}
            onAddSection={(heading, after) => editor && addSection(editor, heading, after)}
            onCheckAnswers={checkAnswers}
            checking={check.isPending}
            checkError={check.error?.message}
            checkedAt={checkedAt}
            onApply={change}
            onUseH1={(h1) => editor && setMainHeading(editor, h1)}
            onUseOutline={() => brief && editor?.commands.setContent(outlineHtml(brief))}
            canUseOutline={isEmptyHtml(draft.content)}
            onRebuild={(pages) => rebuild.mutate(pages, { onSuccess: () => setCheckedAt(null) })}
            rebuilding={rebuild.isPending}
            rebuildError={rebuild.error?.message}
          />
          {briefState.isError && (
            <div className="p-3">
              <Callout tone="bad">{briefState.error.message}</Callout>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const doc = useDocument(id);
  if (doc.isError) {
    return (
      <div className="space-y-3 p-5">
        <Callout tone="bad">{doc.error.message}</Callout>
        <Link href="/editor" className="text-[12px] text-accent hover:underline">
          Back to your drafts
        </Link>
      </div>
    );
  }
  if (!doc.data) {
    return (
      <Empty>
        <LoaderCircle className="mr-1.5 inline size-3.5 animate-spin" /> Opening your draft…
      </Empty>
    );
  }
  return <Workspace key={doc.data.id} doc={doc.data} />;
}
