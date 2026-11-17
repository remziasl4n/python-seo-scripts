/** Display formatting shared by tables and run views. */

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatNumber(value: number): string {
  return numberFormat.format(value);
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isFinite(value) ? formatNumber(value) : "";
  if (typeof value === "boolean") return value ? "✓" : "";
  return String(value);
}

/** "4.2s", "1m 05s", "1h 02m". */
export function formatDuration(start?: string | null, end?: string | null, now = Date.now()): string {
  if (!start) return "";
  const ms = (end ? Date.parse(end) : now) - Date.parse(start);
  if (!Number.isFinite(ms) || ms < 0) return "";
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** "just now", "5 min ago", "3 h ago", then the date. */
export function formatWhen(iso: string, now = Date.now()): string {
  const seconds = (now - Date.parse(iso)) / 1000;
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
