import { describe, expect, it } from "vitest";

import { fieldsFromSchema, initialValues, toInputs } from "./schema-form";

// Exactly what Pydantic produces for the Autocomplete and Query fan-out tools
const autocomplete = {
  properties: {
    seeds: {
      description: "One per line, up to 20. E.g. 'pool cost'.",
      items: { type: "string" },
      maxItems: 20,
      minItems: 1,
      title: "Seed queries",
      type: "array",
    },
    expand: {
      default: "everything",
      description: "Which variations of each seed to request.",
      enum: ["everything", "alphabet", "questions", "seed only"],
      title: "Variations",
      type: "string",
    },
    country: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "Two-letter country code. Empty = the site's country.",
      title: "Country",
    },
  },
  required: ["seeds"],
  title: "AutocompleteInputs",
  type: "object",
};

const fanout = {
  properties: {
    query: { minLength: 2, title: "Seed query or entity", type: "string" },
    per_type: { default: 6, maximum: 15, minimum: 2, title: "Queries per fan-out type", type: "integer" },
    grounded: { default: true, title: "Record Gemini's real searches", type: "boolean" },
  },
  required: ["query"],
  type: "object",
};

describe("fieldsFromSchema", () => {
  it("maps each Pydantic type to a widget", () => {
    const fields = fieldsFromSchema(autocomplete);
    expect(fields.map((f) => [f.name, f.kind])).toEqual([
      ["seeds", "list"],
      ["expand", "select"],
      ["country", "text"],
    ]);
    expect(fields[0]).toMatchObject({ label: "Seed queries", required: true, maxItems: 20 });
    expect(fields[1]?.options).toEqual(["everything", "alphabet", "questions", "seed only"]);
    expect(fields[2]).toMatchObject({ nullable: true, required: false, label: "Country" });
  });

  it("keeps number limits and boolean defaults", () => {
    const [query, perType, grounded] = fieldsFromSchema(fanout);
    expect(query).toMatchObject({ kind: "text", required: true });
    expect(perType).toMatchObject({ kind: "integer", min: 2, max: 15, default: 6 });
    expect(grounded).toMatchObject({ kind: "boolean", default: true });
  });

  it("resolves $ref enums and falls back to a readable label", () => {
    const fields = fieldsFromSchema({
      $defs: { Mode: { enum: ["fast", "full"], type: "string" } },
      properties: { run_mode: { $ref: "#/$defs/Mode", default: "full" } },
    });
    expect(fields[0]).toMatchObject({ kind: "select", label: "Run mode", options: ["fast", "full"] });
  });
});

describe("initialValues / toInputs", () => {
  it("starts from the schema defaults", () => {
    expect(initialValues(fieldsFromSchema(autocomplete))).toEqual({
      seeds: "",
      expand: "everything",
      country: "",
    });
    expect(initialValues(fieldsFromSchema(fanout))).toEqual({
      query: "",
      per_type: "6",
      grounded: true,
    });
  });

  it("turns lines into lists and empty optionals into null", () => {
    const fields = fieldsFromSchema(autocomplete);
    expect(toInputs(fields, { seeds: " pool cost \n\npool size\n", expand: "alphabet", country: "  " })).toEqual({
      seeds: ["pool cost", "pool size"],
      expand: "alphabet",
      country: null,
    });
  });

  it("parses numbers and keeps booleans", () => {
    const fields = fieldsFromSchema(fanout);
    expect(toInputs(fields, { query: "pool cost", per_type: "3", grounded: false })).toEqual({
      query: "pool cost",
      per_type: 3,
      grounded: false,
    });
  });

  it("sends empty required text so the API can say what's missing", () => {
    const fields = fieldsFromSchema(fanout);
    expect(toInputs(fields, { query: "", per_type: "", grounded: true })).toEqual({
      query: "",
      grounded: true,
    });
  });
});
