"use client";

import { Globe, History, LayoutDashboard, Radar, Settings2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { ToolSummary } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useSites, useTools } from "@/lib/queries";

import { useCurrentSite } from "./site-context";
import { ThemeToggle } from "./theme-toggle";
import { Select } from "./ui/field";

function groupTools(tools: ToolSummary[]): [string, ToolSummary[]][] {
  const groups = new Map<string, ToolSummary[]>();
  for (const tool of tools) {
    groups.set(tool.group_title, [...(groups.get(tool.group_title) ?? []), tool]);
  }
  return [...groups.entries()];
}

function NavLink({
  href,
  active,
  children,
  title,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <Link
      href={href}
      title={title}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-7 items-center gap-2 rounded px-2 text-[12.5px] text-foreground/85 hover:bg-surface-2 hover:text-foreground",
        active && "bg-accent-soft font-medium text-accent hover:bg-accent-soft hover:text-accent",
      )}
    >
      {children}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const tools = useTools();
  const sites = useSites();
  const { site, setSite } = useCurrentSite();

  return (
    <aside className="flex h-full w-[212px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex h-11 items-center gap-2 border-b border-border px-3">
        <Radar className="size-4 text-accent" />
        <span className="text-[13px] font-semibold">SEO Toolkit</span>
      </div>

      <div className="space-y-1 border-b border-border p-3">
        <label htmlFor="site" className="text-[10.5px] font-semibold tracking-wider text-muted uppercase">
          Site
        </label>
        <Select
          id="site"
          value={site ?? ""}
          onChange={(e) => setSite(e.target.value)}
          disabled={!sites.data?.sites.length}
        >
          {sites.data?.sites.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} · {s.domain.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
            </option>
          ))}
        </Select>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto p-2">
        <div>
          <NavLink href="/" active={pathname === "/"}>
            <LayoutDashboard className="size-3.5" /> Overview
          </NavLink>
        </div>
        {tools.isError && (
          <p className="flex gap-1.5 px-2 text-[11.5px] text-bad">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" /> {tools.error.message}
          </p>
        )}
        <div>
          <p className="px-2 pb-1 text-[10.5px] font-semibold tracking-wider text-muted uppercase">Workspace</p>
          <NavLink href="/runs" active={pathname === "/runs"}>
            <History className="size-3.5" /> Runs
          </NavLink>
          <NavLink href="/sites" active={pathname.startsWith("/sites")}>
            <Globe className="size-3.5" /> Sites
          </NavLink>
          <NavLink href="/setup" active={pathname === "/setup"}>
            <Settings2 className="size-3.5" /> Setup
          </NavLink>
        </div>
        {groupTools(tools.data ?? []).map(([group, items]) => (
          <div key={group}>
            <p className="px-2 pb-1 text-[10.5px] font-semibold tracking-wider text-muted uppercase">
              {group}
            </p>
            {items.map((tool) => {
              // Tools with their own screen (like the content editor) link straight to it
              const href = tool.page ?? `/tools/${tool.id}`;
              return (
                <NavLink
                  key={tool.id}
                  href={href}
                  active={tool.page ? pathname.startsWith(tool.page) : pathname === href}
                  title={tool.ready ? tool.summary : `Needs ${tool.missing.join(", ")}`}
                >
                  <span
                    className={cn("size-1.5 rounded-full", tool.ready ? "bg-ok" : "bg-warn")}
                    aria-hidden
                  />
                  {tool.title}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <ThemeToggle />
      </div>
    </aside>
  );
}
