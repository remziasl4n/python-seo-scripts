"use client";

/**
 * The editor's right-hand panel: the score, and tabs for the words to use, the questions
 * to answer, the checklist and the brief. Everything says what to do next, in plain words.
 */
import {
  Check,
  CircleDashed,
  CornerDownRight,
  ExternalLink,
  Highlighter,
  ListPlus,
  LoaderCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { type ReactNode, useState } from "react";

import type { Brief, BriefState, CheckScore, Draft, QuestionScore, Score, TermScore } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  checksDone,
  importanceLabel,
  meterTone,
  questionLook,
  questionsDone,
  rangeText,
  scoreTone,
  termLook,
  termsDone,
  type Tone,
} from "@/lib/editor";
import { formatNumber, formatWhen } from "@/lib/format";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Textarea } from "../ui/field";
import { Callout, ProgressBar } from "../ui/panel";

const toneColor: Record<Tone, string> = {
  neutral: "var(--muted)",
  accent: "var(--accent)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  bad: "var(--bad)",
};

const toneText: Record<Tone, string> = {
  neutral: "text-muted",
  accent: "text-accent",
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
};

// --- Score -------------------------------------------------------------------------------

function Ring({ value, tone }: { value: number; tone: Tone }) {
  const radius = 34;
  const length = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 80 80" className="size-[84px] -rotate-90" aria-hidden>
      <circle cx="40" cy="40" r={radius} fill="none" stroke="var(--surface-2)" strokeWidth="7" />
      <circle
        cx="40"
        cy="40"
        r={radius}
        fill="none"
        stroke={toneColor[tone]}
        strokeWidth="7"
        strokeLinecap="round"
        strokeDasharray={`${(length * Math.min(value, 100)) / 100} ${length}`}
        className="transition-[stroke-dasharray] duration-500"
      />
    </svg>
  );
}

const PART_MAX: Record<string, number> = {
  "Words to use": 45,
  "Questions answered": 25,
  Checklist: 20,
  Length: 10,
};

function Meter({ label, count, min, max, unit }: { label: string; count: number; min: number; max: number; unit: string }) {
  const tone = meterTone(count, min, max);
  return (
    <div className="min-w-0 flex-1 rounded border border-border px-2.5 py-1.5">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="tabular text-[13px] font-semibold">
        <span className={toneText[tone]}>{formatNumber(count)}</span>
        <span className="text-[11px] font-normal text-muted">
          {" "}
          / {formatNumber(min)}–{formatNumber(max)} {unit}
        </span>
      </p>
    </div>
  );
}

function ScoreCard({ score, scoring }: { score?: Score; scoring: boolean }) {
  const value = score?.score ?? 0;
  const tone = score ? scoreTone(value) : "neutral";
  return (
    <div className="space-y-3 border-b border-border p-3">
      <div className="flex items-center gap-3">
        <div className="relative">
          <Ring value={value} tone={tone} />
          <span className="tabular absolute inset-0 flex items-center justify-center text-[22px] font-semibold" aria-label={`Score ${value} out of 100`}>
            {score ? value : "–"}
          </span>
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="flex items-center gap-1.5 text-[13px] font-semibold">
            <span className={toneText[tone]}>{score?.label ?? "Waiting for the brief"}</span>
            {scoring && <LoaderCircle className="size-3 animate-spin text-muted" aria-label="Updating" />}
          </p>
          {Object.entries(PART_MAX).map(([name, max]) => (
            <div key={name} className="flex items-center gap-2 text-[11px]">
              <span className="w-[108px] shrink-0 text-muted">{name}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent transition-[width] duration-500"
                  style={{ width: `${((score?.parts[name] ?? 0) / max) * 100}%` }}
                />
              </div>
              <span className="tabular w-9 text-right text-muted">
                {score?.parts[name] ?? 0}/{max}
              </span>
            </div>
          ))}
        </div>
      </div>
      {score && (
        <div className="flex gap-2">
          <Meter label="Words" unit="" {...score.words} />
          <Meter label="Sections" unit="" {...score.headings} />
        </div>
      )}
    </div>
  );
}

// --- Words to use ------------------------------------------------------------------------

type TermFilter = "all" | "todo" | "over";

function TermRow({ term, active, onClick }: { term: TermScore; active: boolean; onClick: () => void }) {
  const look = termLook[term.status];
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        title={`${look.label}. ${term.pages ? `Used by ${term.pages} of the top pages.` : "Suggested by Gemini."} Click to highlight it in your text.`}
        className={cn(
          "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[12.5px] hover:bg-surface-2",
          active && "bg-warn-soft hover:bg-warn-soft",
        )}
      >
        <span className={cn("min-w-0 flex-1 truncate", term.main && "font-semibold")}>{term.term}</span>
        {active && <Highlighter className="size-3 shrink-0 text-warn" aria-hidden />}
        <span
          className={cn(
            "tabular inline-flex h-[18px] shrink-0 items-center rounded px-1.5 text-[11px] font-medium",
            look.tone === "neutral" && "bg-surface-2 text-muted",
            look.tone === "warn" && "bg-warn-soft text-warn",
            look.tone === "ok" && "bg-ok-soft text-ok",
            look.tone === "bad" && "bg-bad-soft text-bad",
          )}
        >
          {term.count} / {rangeText(term.min, term.max)}
        </span>
      </button>
    </li>
  );
}

function TermsTab({
  terms,
  highlighted,
  onHighlight,
}: {
  terms: TermScore[];
  highlighted: string | null;
  onHighlight: (term: string | null) => void;
}) {
  const [filter, setFilter] = useState<TermFilter>("all");
  const shown = terms.filter((t) =>
    filter === "all" ? true : filter === "todo" ? t.status === "missing" || t.status === "low" : t.status === "over",
  );
  const groups: [string, TermScore[]][] = [
    ["Main keyword", shown.filter((t) => t.main)],
    ...(["must", "should", "nice"] as const).map(
      (level) => [importanceLabel[level], shown.filter((t) => !t.main && t.importance === level)] as [string, TermScore[]],
    ),
  ];
  const counts = {
    all: terms.length,
    todo: terms.filter((t) => t.status === "missing" || t.status === "low").length,
    over: terms.filter((t) => t.status === "over").length,
  };
  return (
    <div className="space-y-2 p-3">
      <p className="text-[11.5px] leading-snug text-muted">
        Words and phrases the top pages use, and how often to use each one (yours / target). Click one to
        highlight it in your text.
      </p>
      <div className="flex gap-1" role="radiogroup" aria-label="Show">
        {(
          [
            ["all", "All"],
            ["todo", "To add"],
            ["over", "Too often"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={filter === value}
            onClick={() => setFilter(value)}
            className={cn(
              "h-6 rounded px-2 text-[11.5px] font-medium",
              filter === value ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2",
            )}
          >
            {label} <span className="tabular opacity-70">{counts[value]}</span>
          </button>
        ))}
      </div>
      {groups.map(
        ([label, items]) =>
          items.length > 0 && (
            <div key={label}>
              <p className="px-2 pt-1 pb-0.5 text-[10.5px] font-semibold tracking-wider text-muted uppercase">{label}</p>
              <ul>
                {items.map((term) => (
                  <TermRow
                    key={term.term}
                    term={term}
                    active={highlighted === term.term}
                    onClick={() => onHighlight(highlighted === term.term ? null : term.term)}
                  />
                ))}
              </ul>
            </div>
          ),
      )}
      {shown.length === 0 && (
        <p className="py-4 text-center text-[12px] text-muted">
          {filter === "over" ? "Nothing is used too often." : "Every word is used enough. Nice."}
        </p>
      )}
    </div>
  );
}

// --- Questions ---------------------------------------------------------------------------

function QuestionCard({
  question,
  onGoTo,
  onAdd,
}: {
  question: QuestionScore;
  onGoTo: (heading: string) => void;
  onAdd: (heading: string, after: string) => void;
}) {
  const look = questionLook[question.status];
  return (
    <li className="space-y-1.5 rounded border border-border p-2.5">
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[12.5px] font-medium leading-snug">{question.heading}</p>
        <Badge tone={look.tone}>{look.label}</Badge>
      </div>
      {question.what_to_say && question.status !== "answered" && (
        <p className="text-[11.5px] leading-snug text-muted">{question.what_to_say}</p>
      )}
      {question.fix && (
        <p className="flex gap-1.5 rounded bg-warn-soft px-2 py-1.5 text-[11.5px] leading-snug">
          <Sparkles className="mt-0.5 size-3 shrink-0 text-warn" aria-hidden />
          <span>{question.fix}</span>
        </p>
      )}
      {question.searches.length > 0 && (
        <p className="text-[11px] leading-snug text-muted">
          Answers: {question.searches.map((s) => `“${s}”`).join(", ")}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {question.section ? (
          <Button variant="ghost" className="h-6 px-1.5 text-[11.5px]" onClick={() => onGoTo(question.section ?? "")}>
            <CornerDownRight className="size-3" /> Go to “{question.section}”
          </Button>
        ) : (
          <Button
            variant="ghost"
            className="h-6 px-1.5 text-[11.5px] text-accent"
            onClick={() => onAdd(question.heading, question.place_after ?? "")}
          >
            <ListPlus className="size-3" />
            {question.place_after ? `Add after “${question.place_after}”` : "Add as a heading"}
          </Button>
        )}
      </div>
    </li>
  );
}

function QuestionsTab({
  questions,
  onGoTo,
  onAdd,
  onCheck,
  checking,
  checkError,
  checkedAt,
}: {
  questions: QuestionScore[];
  onGoTo: (heading: string) => void;
  onAdd: (heading: string, after: string) => void;
  onCheck: () => void;
  checking: boolean;
  checkError?: string;
  checkedAt?: string | null;
}) {
  return (
    <div className="space-y-2 p-3">
      <p className="text-[11.5px] leading-snug text-muted">
        What readers want to know, in the order they need it. Give each one a heading and answer it in the first
        sentence underneath.
      </p>
      <div className="flex items-center gap-2">
        <Button variant="primary" onClick={onCheck} disabled={checking}>
          {checking ? <LoaderCircle className="size-3 animate-spin" /> : <Sparkles className="size-3" />}
          {checking ? "Checking…" : "Check my answers"}
        </Button>
        <span className="text-[11px] text-muted">
          {checkedAt ? `Checked ${formatWhen(checkedAt)}` : "Gemini reads your draft and says what's missing."}
        </span>
      </div>
      {checkError && <Callout tone="bad">{checkError}</Callout>}
      <ol className="space-y-2">
        {questions.map((q) => (
          <QuestionCard key={q.heading} question={q} onGoTo={onGoTo} onAdd={onAdd} />
        ))}
      </ol>
    </div>
  );
}

// --- Checklist ---------------------------------------------------------------------------

function ChecklistTab({ checks, onGoTo }: { checks: CheckScore[]; onGoTo: (heading: string) => void }) {
  const groups = [...new Set(checks.map((c) => c.group))];
  return (
    <div className="space-y-3 p-3">
      {groups.map((group) => (
        <div key={group}>
          <p className="pb-1 text-[10.5px] font-semibold tracking-wider text-muted uppercase">{group}</p>
          <ul className="space-y-1">
            {checks
              .filter((c) => c.group === group)
              .map((check) => (
                <li key={check.id} className="text-[12.5px]">
                  <p className="flex items-start gap-1.5">
                    {check.done ? (
                      <Check className="mt-0.5 size-3.5 shrink-0 text-ok" aria-label="Done" />
                    ) : (
                      <CircleDashed className="mt-0.5 size-3.5 shrink-0 text-muted" aria-label="To do" />
                    )}
                    <span className={cn(check.done && "text-muted")}>{check.label}</span>
                  </p>
                  {!check.done && (check.fixes ?? []).length > 0 && (
                    <ul className="mt-1 ml-5 space-y-1">
                      {(check.fixes ?? []).map((fix) => (
                        <li key={fix.text} className="text-[11.5px] leading-snug text-muted">
                          {fix.text}{" "}
                          {fix.section && (
                            <button
                              type="button"
                              onClick={() => onGoTo(fix.section ?? "")}
                              className="font-medium text-accent hover:underline"
                            >
                              Go there
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// --- Brief -------------------------------------------------------------------------------

function Suggestion({ label, value, onUse }: { label: string; value: string; onUse: () => void }) {
  if (!value) return null;
  return (
    <div className="space-y-0.5">
      <p className="flex items-center justify-between text-[11px] text-muted">
        {label}
        <button type="button" onClick={onUse} className="font-medium text-accent hover:underline">
          Use this
        </button>
      </p>
      <p className="text-[12.5px] leading-snug">{value}</p>
    </div>
  );
}

function BriefTab({
  brief,
  onApply,
  onUseH1,
  onUseOutline,
  canUseOutline,
  onRebuild,
  rebuilding,
  rebuildError,
}: {
  brief: Brief;
  onApply: (changes: Partial<Draft>) => void;
  onUseH1: (h1: string) => void;
  onUseOutline: () => void;
  canUseOutline: boolean;
  onRebuild: (pages: string[]) => void;
  rebuilding: boolean;
  rebuildError?: string;
}) {
  const [pages, setPages] = useState("");
  return (
    <div className="space-y-4 p-3 text-[12.5px]">
      <dl className="grid grid-cols-2 gap-2">
        <div>
          <dt className="text-[11px] text-muted">The reader wants to</dt>
          <dd className="font-medium">{brief.reader_wants}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted">Kind of page</dt>
          <dd className="font-medium capitalize">{brief.page_type}</dd>
        </div>
      </dl>

      {canUseOutline && (
        <Callout>
          <p className="mb-2">Starting from scratch? Put the main heading and every question in place, with a note on what to write under each.</p>
          <Button variant="primary" onClick={onUseOutline}>
            <ListPlus className="size-3" /> Start with the suggested outline
          </Button>
        </Callout>
      )}

      <div className="space-y-2">
        <p className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">Suggested</p>
        <Suggestion label="Page title" value={brief.title} onUse={() => onApply({ title: brief.title })} />
        <Suggestion label="Main heading (H1)" value={brief.h1} onUse={() => onUseH1(brief.h1)} />
        <Suggestion
          label="Meta description"
          value={brief.meta_description}
          onUse={() => onApply({ meta_description: brief.meta_description })}
        />
        <Suggestion label="Web address" value={`/${brief.url_slug}/`} onUse={() => onApply({ url_slug: brief.url_slug })} />
      </div>

      <div className="space-y-1">
        <p className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">
          Layout for a page to {brief.reader_wants.toLowerCase()}
        </p>
        <ul className="space-y-1">
          {brief.layout.map((item) => (
            <li key={item} className="flex gap-1.5 leading-snug">
              <input type="checkbox" className="mt-0.5 size-3.5 shrink-0 accent-[var(--accent)]" aria-label={item} />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-1">
        <p className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">
          Based on {brief.pages.length} top {brief.pages.length === 1 ? "page" : "pages"}
        </p>
        {brief.pages.length === 0 && (
          <p className="text-[11.5px] text-muted">No top pages could be read, so the words to use are Gemini&apos;s suggestions.</p>
        )}
        <ul className="space-y-1">
          {brief.pages.map((page) => (
            <li key={page.url}>
              <details className="group">
                <summary className="flex cursor-pointer list-none items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate">{page.title}</span>
                  <span className="tabular shrink-0 text-[11px] text-muted">{formatNumber(page.word_count)} words</span>
                </summary>
                <div className="mt-1 ml-2 space-y-1 border-l border-border pl-2 text-[11.5px] text-muted">
                  <a href={page.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                    {page.domain} <ExternalLink className="size-3" />
                  </a>
                  {page.headings.length > 0 && (
                    <ul className="list-disc pl-4">
                      {page.headings.map((h, i) => (
                        <li key={`${h}-${i}`}>{h}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </details>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-1.5">
        <p className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">Learn from other pages</p>
        <Textarea
          aria-label="Top pages to learn from"
          placeholder={"Paste the top Google results for your keyword, one per line"}
          value={pages}
          onChange={(e) => setPages(e.target.value)}
        />
        <Button onClick={() => onRebuild(pages.split("\n").map((p) => p.trim()).filter(Boolean))} disabled={rebuilding}>
          <RefreshCw className={cn("size-3", rebuilding && "animate-spin")} /> Rebuild the brief
        </Button>
        {rebuildError && <Callout tone="bad">{rebuildError}</Callout>}
      </div>
    </div>
  );
}

// --- The panel ---------------------------------------------------------------------------

type Tab = "words" | "questions" | "checklist" | "brief";

function BriefProgress({ state, onRetry }: { state?: BriefState; onRetry: () => void }) {
  const run = state?.run;
  if (run?.status === "failed") {
    return (
      <div className="space-y-2 p-3">
        <Callout tone="bad">{run.error ?? "The brief couldn't be built."}</Callout>
        <Button onClick={onRetry}>
          <RefreshCw className="size-3" /> Try again
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2 p-3">
      <p className="flex items-center gap-2 text-[12.5px] font-medium">
        <LoaderCircle className="size-3.5 animate-spin text-accent" /> Building your brief…
      </p>
      <ProgressBar value={run?.progress ?? 0} />
      <p className="text-[11.5px] text-muted">{run?.message || "Starting…"}</p>
      <p className="text-[11.5px] leading-snug text-muted">
        Reading the top pages and the searches around your keyword. This takes a minute or two the first time.
        Start writing meanwhile: your score appears as soon as it&apos;s ready.
      </p>
    </div>
  );
}

export interface ScorePanelProps {
  score?: Score;
  scoring: boolean;
  briefState?: BriefState;
  highlighted: string | null;
  onHighlight: (term: string | null) => void;
  onGoTo: (heading: string) => void;
  onAddSection: (heading: string, after: string) => void;
  onCheckAnswers: () => void;
  checking: boolean;
  checkError?: string;
  checkedAt?: string | null;
  onApply: (changes: Partial<Draft>) => void;
  onUseH1: (h1: string) => void;
  onUseOutline: () => void;
  canUseOutline: boolean;
  onRebuild: (pages: string[]) => void;
  rebuilding: boolean;
  rebuildError?: string;
}

export function ScorePanel(props: ScorePanelProps) {
  const [tab, setTab] = useState<Tab>("words");
  const { score, briefState } = props;
  const brief = briefState?.brief;
  if (!brief) {
    return <BriefProgress state={briefState} onRetry={() => props.onRebuild((briefState?.run?.inputs.pages as string[]) ?? [])} />;
  }

  const tabs: [Tab, string, ReactNode][] = [
    ["words", "Words", score && `${termsDone(score.terms)}/${score.terms.length}`],
    ["questions", "Questions", score && `${questionsDone(score.questions)}/${score.questions.length}`],
    ["checklist", "Checklist", score && `${checksDone(score.checks)}/${score.checks.length}`],
    ["brief", "Brief", null],
  ];

  return (
    <div>
      <ScoreCard score={score} scoring={props.scoring} />
      <div role="tablist" aria-label="Guidance" className="sticky top-0 z-10 flex border-b border-border bg-background px-1">
        {tabs.map(([value, label, count]) => (
          <button
            key={value}
            role="tab"
            type="button"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              "-mb-px flex-auto border-b-2 px-1.5 py-2 text-[12px] font-medium whitespace-nowrap",
              tab === value ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground",
            )}
          >
            {label} {count && <span className="tabular text-[11px] text-muted">{count}</span>}
          </button>
        ))}
      </div>
      {!score ? (
        <p className="p-3 text-[12px] text-muted">Scoring your draft…</p>
      ) : tab === "words" ? (
        <TermsTab terms={score.terms} highlighted={props.highlighted} onHighlight={props.onHighlight} />
      ) : tab === "questions" ? (
        <QuestionsTab
          questions={score.questions}
          onGoTo={props.onGoTo}
          onAdd={props.onAddSection}
          onCheck={props.onCheckAnswers}
          checking={props.checking}
          checkError={props.checkError}
          checkedAt={props.checkedAt}
        />
      ) : tab === "checklist" ? (
        <ChecklistTab checks={score.checks} onGoTo={props.onGoTo} />
      ) : (
        <BriefTab
          brief={brief}
          onApply={props.onApply}
          onUseH1={props.onUseH1}
          onUseOutline={props.onUseOutline}
          canUseOutline={props.canUseOutline}
          onRebuild={props.onRebuild}
          rebuilding={props.rebuilding}
          rebuildError={props.rebuildError}
        />
      )}
    </div>
  );
}
