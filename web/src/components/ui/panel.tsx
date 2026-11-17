import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A bordered box with an optional header row: the main layout unit. */
export function Panel({
  title,
  actions,
  className,
  bodyClassName,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("rounded-md border border-border bg-background", className)}>
      {(title || actions) && (
        <header className="flex h-9 items-center justify-between gap-2 border-b border-border px-3">
          <h2 className="text-[12px] font-semibold tracking-wide text-foreground">{title}</h2>
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn("p-3", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Callout({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "warn" | "bad";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded border px-3 py-2 text-[12px] whitespace-pre-line",
        tone === "neutral" && "border-border bg-surface text-foreground",
        tone === "warn" && "border-warn/30 bg-warn-soft text-foreground",
        tone === "bad" && "border-bad/30 bg-bad-soft text-foreground",
      )}
    >
      {children}
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-300"
        style={{ width: `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%` }}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-[12px] text-muted">{children}</p>;
}
