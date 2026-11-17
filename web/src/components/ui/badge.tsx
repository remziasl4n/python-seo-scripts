import type { ReactNode } from "react";

import type { Check, RunStatus } from "@/lib/api";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "accent" | "ok" | "warn" | "bad";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  accent: "bg-accent-soft text-accent",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-[18px] items-center rounded px-1.5 text-[11px] font-medium whitespace-nowrap",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

const statusTone: Record<RunStatus, Tone> = {
  queued: "neutral",
  running: "accent",
  done: "ok",
  failed: "bad",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return <Badge tone={statusTone[status]}>{status}</Badge>;
}

const checkLook: Record<Check["status"], [Tone, string]> = {
  ok: ["ok", "ok"],
  warn: ["warn", "check"],
  fail: ["bad", "problem"],
  off: ["neutral", "not set"],
};

export function CheckBadge({ status }: { status: Check["status"] }) {
  const [tone, label] = checkLook[status];
  return <Badge tone={tone}>{label}</Badge>;
}
