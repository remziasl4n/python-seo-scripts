import { describe, expect, it } from "vitest";

import type { Brief } from "./api";
import { findTerm, fingerprint, isEmptyHtml, meterTone, outlineHtml, rangeText, scoreTone, stem } from "./editor";

describe("stem", () => {
  it("folds plurals and possessives like the Python scorer", () => {
    expect(["pools", "pool's", "batteries", "boxes", "glass", "bus", "costs", "2026"].map(stem)).toEqual([
      "pool",
      "pool",
      "battery",
      "box",
      "glass",
      "bus",
      "cost",
      "2026",
    ]);
  });
});

describe("findTerm", () => {
  const text = "Inground pools are popular. An inground pool costs more, pool heater. Pool pump";

  it("finds every place a phrase is used, ignoring plurals and case", () => {
    const found = findTerm(text, "inground pool").map(([a, b]) => text.slice(a, b));
    expect(found).toEqual(["Inground pools", "inground pool"]);
  });

  it("doesn't join words across punctuation", () => {
    expect(findTerm(text, "heater pool")).toEqual([]);
    expect(findTerm(text, "popular an")).toEqual([]);
  });

  it("matches whole words only", () => {
    expect(findTerm("A poolside bar", "pool")).toEqual([]);
    expect(findTerm(text, "")).toEqual([]);
  });
});

describe("labels", () => {
  it("formats ranges and tones", () => {
    expect(rangeText(2, 5)).toBe("2–5");
    expect(rangeText(3, 3)).toBe("3");
    expect([0, 1, 3, 9].map((n) => meterTone(n, 2, 4))).toEqual(["neutral", "warn", "ok", "bad"]);
    expect([90, 70, 50, 10].map(scoreTone)).toEqual(["ok", "accent", "warn", "bad"]);
  });
});

describe("outline", () => {
  it("turns the brief's questions into headings, safely", () => {
    const brief = {
      keyword: "pool cost",
      h1: "Pool cost <2026>",
      questions: [{ heading: "How much & why?", searches: [], what_to_say: "" }],
    } as unknown as Brief;
    expect(outlineHtml(brief)).toBe("<h1>Pool cost &lt;2026&gt;</h1><p></p><h2>How much &amp; why?</h2><p></p>");
  });

  it("knows an empty editor", () => {
    expect(isEmptyHtml("<p></p>")).toBe(true);
    expect(isEmptyHtml("<p></p><p></p>")).toBe(true);
    expect(isEmptyHtml("<p>Hi</p>")).toBe(false);
  });
});

describe("fingerprint", () => {
  it("changes when the draft does", () => {
    const a = { name: "x", content: "<p>Pool</p>" };
    expect(fingerprint(a)).toBe(fingerprint({ ...a }));
    expect(fingerprint(a)).not.toBe(fingerprint({ ...a, content: "<p>Pools</p>" }));
  });
});
