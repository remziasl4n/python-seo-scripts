import { describe, expect, it } from "vitest";

import { formatCell, formatDuration, formatWhen } from "./format";

describe("formatCell", () => {
  it("formats each kind of value for a table", () => {
    expect(formatCell(1234.5)).toBe("1,234.5");
    expect(formatCell(true)).toBe("✓");
    expect(formatCell(false)).toBe("");
    expect(formatCell(null)).toBe("");
    expect(formatCell(Number.NaN)).toBe("");
    expect(formatCell("pool cost")).toBe("pool cost");
  });
});

describe("formatDuration", () => {
  const start = "2026-11-15T10:00:00Z";
  it("uses the shortest readable unit", () => {
    expect(formatDuration(start, "2026-11-15T10:00:04.2Z")).toBe("4.2s");
    expect(formatDuration(start, "2026-11-15T10:01:05Z")).toBe("1m 05s");
    expect(formatDuration(start, "2026-11-15T11:02:00Z")).toBe("1h 02m");
  });
  it("counts up to now while a run is going, and is blank before it starts", () => {
    expect(formatDuration(start, null, Date.parse("2026-11-15T10:00:30Z"))).toBe("30.0s");
    expect(formatDuration(null, null)).toBe("");
  });
});

describe("formatWhen", () => {
  const now = Date.parse("2026-11-15T12:00:00Z");
  it("is relative for recent times", () => {
    expect(formatWhen("2026-11-15T11:59:40Z", now)).toBe("just now");
    expect(formatWhen("2026-11-15T11:55:00Z", now)).toBe("5 min ago");
    expect(formatWhen("2026-11-15T09:00:00Z", now)).toBe("3 h ago");
    expect(formatWhen("2026-11-01T09:00:00Z", now)).toBe("1 Nov 2026");
  });
});
