"use client";

import { FilePlus2, LoaderCircle, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useCurrentSite } from "@/components/site-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { Callout, Empty, Panel } from "@/components/ui/panel";
import { ApiError, type FieldError } from "@/lib/api";
import { scoreTone } from "@/lib/editor";
import { formatNumber, formatWhen } from "@/lib/format";
import { useCreateDocument, useDeleteDocument, useDocuments } from "@/lib/queries";

function NewDraft() {
  const router = useRouter();
  const { site } = useCurrentSite();
  const create = useCreateDocument();
  const [keyword, setKeyword] = useState("");
  const [importUrl, setImportUrl] = useState("");
  const [pages, setPages] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    setErrors([]);
    setError(null);
    if (keyword.trim().length < 2) {
      setErrors([{ field: "keyword", label: "Keyword", message: "Enter the search you want this page to rank for." }]);
      return;
    }
    create.mutate(
      {
        keyword,
        site,
        import_url: importUrl.trim() || null,
        pages: pages.split("\n").map((p) => p.trim()).filter(Boolean),
      },
      {
        onSuccess: (doc) => router.push(`/editor/${doc.id}`),
        onError: (e) => {
          if (e instanceof ApiError && e.fieldErrors.length) setErrors(e.fieldErrors);
          else setError(e.message);
        },
      },
    );
  }

  const errorFor = (field: string) => errors.find((e) => e.field === field || e.field.startsWith(`${field}.`))?.message;

  return (
    <Panel title="New draft">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Field
          label="Keyword"
          htmlFor="keyword"
          required
          hint="The search you want this page to rank for, e.g. 'inground pool cost'."
          error={errorFor("keyword")}
        >
          <Input id="keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} aria-invalid={Boolean(errorFor("keyword"))} />
        </Field>
        <Field
          label="Improve an existing page (optional)"
          htmlFor="import_url"
          hint="Its address. The text is copied into the editor so you can improve it."
        >
          <Input
            id="import_url"
            value={importUrl}
            placeholder="https://www.example.com/your-page/"
            onChange={(e) => setImportUrl(e.target.value)}
          />
        </Field>
        <Field
          label="Top pages to learn from (optional)"
          htmlFor="pages"
          hint="Search Google for your keyword and paste the top results, one per line. Leave empty to use the pages Google's AI cites."
          error={errorFor("pages")}
        >
          <Textarea id="pages" value={pages} onChange={(e) => setPages(e.target.value)} aria-invalid={Boolean(errorFor("pages"))} />
        </Field>
        {error && <Callout tone="bad">{error}</Callout>}
        <Button type="submit" variant="primary" disabled={create.isPending || !site}>
          {create.isPending ? <LoaderCircle className="size-3 animate-spin" /> : <FilePlus2 className="size-3" />}
          {create.isPending ? (importUrl ? "Reading your page…" : "Creating…") : "Create draft"}
        </Button>
      </form>
    </Panel>
  );
}

function DeleteButton({ id, name }: { id: string; name: string }) {
  const remove = useDeleteDocument();
  const [sure, setSure] = useState(false);
  if (!sure) {
    return (
      <Button variant="ghost" className="h-6 px-1.5" aria-label={`Delete ${name}`} onClick={() => setSure(true)}>
        <Trash2 className="size-3" />
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <Button className="h-6 border-bad/40 px-2 text-bad" onClick={() => remove.mutate(id)} disabled={remove.isPending}>
        Delete
      </Button>
      <Button variant="ghost" className="h-6 px-2" onClick={() => setSure(false)}>
        Keep
      </Button>
    </span>
  );
}

export default function EditorHome() {
  const documents = useDocuments();
  return (
    <>
      <PageHeader
        eyebrow="Content"
        title="Content editor"
        description="Write a page with a live score: the words to use, the questions to answer, and what to fix."
      />
      <div className="grid gap-4 p-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <NewDraft />
        <Panel title="Drafts" bodyClassName="p-0">
          {documents.isError ? (
            <div className="p-3">
              <Callout tone="bad">{documents.error.message}</Callout>
            </div>
          ) : !documents.data ? (
            <Empty>Loading…</Empty>
          ) : documents.data.length === 0 ? (
            <Empty>No drafts yet. Enter a keyword to start your first one.</Empty>
          ) : (
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] text-muted">
                  <th className="px-3 py-2 font-semibold">Draft</th>
                  <th className="px-3 py-2 font-semibold">Keyword</th>
                  <th className="px-3 py-2 text-right font-semibold">Score</th>
                  <th className="px-3 py-2 text-right font-semibold">Words</th>
                  <th className="px-3 py-2 font-semibold">Saved</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {documents.data.map((doc) => (
                  <tr key={doc.id} className="border-b border-border/60 last:border-0 hover:bg-surface">
                    <td className="px-3 py-1.5">
                      <Link href={`/editor/${doc.id}`} className="font-medium text-accent hover:underline">
                        {doc.name}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-muted">{doc.keyword}</td>
                    <td className="px-3 py-1.5 text-right">
                      {doc.score === null ? <span className="text-muted">—</span> : <Badge tone={scoreTone(doc.score)}>{doc.score}</Badge>}
                    </td>
                    <td className="tabular px-3 py-1.5 text-right">{formatNumber(doc.word_count)}</td>
                    <td className="px-3 py-1.5 text-muted">{formatWhen(doc.updated_at)}</td>
                    <td className="px-3 py-1.5 text-right">
                      <DeleteButton id={doc.id} name={doc.name} />
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
