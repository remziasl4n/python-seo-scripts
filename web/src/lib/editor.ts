/**
 * Content editor helpers: finding a word or phrase in the text (the same way the Python
 * scorer counts it: plurals fold, phrases stop at punctuation), labels and colours for
 * each status, and the starter outline. Pure functions, unit-tested.
 */
import type { Brief, CheckScore, QuestionScore, TermScore } from "./api";

const WORD = /[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu;
const PHRASE_BREAK = /[.!?;:,()[\]{}|•–—"“”]/;

/** Fold English plurals and possessives, so "pools" and "pool's" match "pool" (core/content.py). */
export function stem(word: string): string {
  let w = word.toLowerCase().replace(/’/g, "'");
  if (w.endsWith("'s")) w = w.slice(0, -2);
  else if (w.endsWith("'")) w = w.slice(0, -1);
  if (w.length <= 3 || /^\d+$/.test(w)) return w;
  if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
  if (/(sses|ches|shes|xes|zes)$/.test(w)) return w.slice(0, -2);
  if (w.endsWith("s") && !/(ss|us|is|os)$/.test(w)) return w.slice(0, -1);
  return w;
}

interface Token {
  stem: string;
  start: number;
  end: number;
  chunk: number; // tokens in different chunks are separated by punctuation
}

function tokens(text: string): Token[] {
  const found: Token[] = [];
  let chunk = 0;
  let last = 0;
  for (const match of text.matchAll(WORD)) {
    const start = match.index ?? 0;
    if (PHRASE_BREAK.test(text.slice(last, start))) chunk += 1;
    found.push({ stem: stem(match[0]), start, end: start + match[0].length, chunk });
    last = start + match[0].length;
  }
  return found;
}

/** Where `term` appears in `text`, as [start, end) character ranges. */
export function findTerm(text: string, term: string): [number, number][] {
  const wanted = [...term.matchAll(WORD)].map((m) => stem(m[0]));
  if (!wanted.length) return [];
  const all = tokens(text);
  const ranges: [number, number][] = [];
  for (let i = 0; i + wanted.length <= all.length; i++) {
    const window = all.slice(i, i + wanted.length);
    const first = window[0];
    const last = window[window.length - 1];
    if (first && last && window.every((t, j) => t.stem === wanted[j] && t.chunk === first.chunk)) {
      ranges.push([first.start, last.end]);
    }
  }
  return ranges;
}

export function countWords(text: string): number {
  return [...text.matchAll(WORD)].length;
}

// --- Labels and colours ----------------------------------------------------------------

export type Tone = "neutral" | "accent" | "ok" | "warn" | "bad";

export const termLook: Record<TermScore["status"], { tone: Tone; label: string }> = {
  missing: { tone: "neutral", label: "Not used yet" },
  low: { tone: "warn", label: "Use it more" },
  good: { tone: "ok", label: "Just right" },
  over: { tone: "bad", label: "Used too often" },
};

export const questionLook: Record<QuestionScore["status"], { tone: Tone; label: string }> = {
  missing: { tone: "neutral", label: "Not covered" },
  heading: { tone: "accent", label: "Has a heading" },
  partly: { tone: "warn", label: "Partly answered" },
  answered: { tone: "ok", label: "Answered" },
};

export const importanceLabel: Record<TermScore["importance"], string> = {
  must: "Must use",
  should: "Should use",
  nice: "Nice to have",
};

export function scoreTone(score: number): Tone {
  if (score >= 85) return "ok";
  if (score >= 65) return "accent";
  if (score >= 40) return "warn";
  return "bad";
}

/** "3–6", or "3" when the range is a single number. */
export function rangeText(min: number, max: number): string {
  return min === max ? String(min) : `${min}–${max}`;
}

/** Where a count sits against its target: under, inside or over. */
export function meterTone(count: number, min: number, max: number): Tone {
  if (count === 0) return "neutral";
  if (count < min) return "warn";
  return count > max ? "bad" : "ok";
}

export function termsDone(terms: TermScore[]): number {
  return terms.filter((t) => t.status === "good").length;
}

export function questionsDone(questions: QuestionScore[]): number {
  return questions.filter((q) => q.status === "answered" || q.status === "heading").length;
}

export function checksDone(checks: CheckScore[]): number {
  return checks.filter((c) => c.done).length;
}

// --- Starting points -------------------------------------------------------------------

function escape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** The brief's outline as editor content: the main heading, then each question as an H2. */
export function outlineHtml(brief: Brief): string {
  const sections = brief.questions.map((q) => `<h2>${escape(q.heading)}</h2><p></p>`).join("");
  return `<h1>${escape(brief.h1 || brief.keyword)}</h1><p></p>${sections}`;
}

/** A short fingerprint of a draft, so each version is scored once (FNV-1a). */
export function fingerprint(value: unknown): string {
  const text = JSON.stringify(value);
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${text.length}-${(hash >>> 0).toString(36)}`;
}

/** True when the editor holds nothing but empty paragraphs. */
export function isEmptyHtml(html: string): boolean {
  return html.replace(/<p><\/p>|<p><br\s*\/?><\/p>|\s/g, "") === "";
}
