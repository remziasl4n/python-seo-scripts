import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-end justify-between gap-4 border-b border-border px-5 py-3">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">{eyebrow}</p>
        )}
        <h1 className="text-[16px] font-semibold">{title}</h1>
        {description && <p className="mt-0.5 text-[12px] text-muted">{description}</p>}
      </div>
      {actions}
    </header>
  );
}
