/**
 * Turn a tool's input JSON Schema (from its Pydantic `Inputs`) into form fields, and form
 * values back into the inputs the API expects. The form component only draws widgets.
 *
 *   string                    -> text box ("Leave empty to use the default" when optional)
 *   array of strings          -> text area, one item per line
 *   integer / number          -> number box with min / max
 *   boolean                   -> checkbox
 *   enum (Python Literal)     -> dropdown; "x-labels" gives each choice a friendly name
 *   "x-widget": "run"         -> picker of finished runs ("x-tools" limits which tools)
 */

export type FieldKind = "text" | "list" | "integer" | "number" | "boolean" | "select" | "run";

export interface FormField {
  name: string;
  label: string;
  description?: string;
  kind: FieldKind;
  required: boolean;
  nullable: boolean; // empty means "use the default" (Python `X | None`)
  options?: string[];
  optionLabels?: Record<string, string>;
  tools?: string[]; // for run pickers: which tools' runs to offer
  min?: number;
  max?: number;
  maxItems?: number;
  default?: unknown;
}

export type FormValues = Record<string, string | boolean>;

interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
  maxItems?: number;
  $ref?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  $defs?: Record<string, JsonSchema>;
  "x-labels"?: Record<string, string>;
  "x-widget"?: string;
  "x-tools"?: string[];
}

function resolve(node: JsonSchema, root: JsonSchema): JsonSchema {
  if (!node.$ref) return node;
  const name = node.$ref.split("/").pop() ?? "";
  return { ...(root.$defs?.[name] ?? {}), ...node, $ref: undefined };
}

function kindOf(node: JsonSchema): FieldKind {
  if (node["x-widget"] === "run") return "run";
  if (node.enum) return "select";
  const type = Array.isArray(node.type) ? node.type.find((t) => t !== "null") : node.type;
  if (type === "boolean") return "boolean";
  if (type === "integer") return "integer";
  if (type === "number") return "number";
  if (type === "array") return "list";
  return "text";
}

function humanize(name: string): string {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function fieldsFromSchema(schema: Record<string, unknown>): FormField[] {
  const root = schema as JsonSchema;
  const required = new Set(root.required ?? []);
  return Object.entries(root.properties ?? {}).map(([name, raw]) => {
    const outer = resolve(raw, root);
    const variants = (outer.anyOf ?? [outer]).map((v) => resolve(v, root));
    const nullable = variants.some((v) => v.type === "null");
    const base = variants.find((v) => v.type !== "null") ?? outer;
    const node = { ...base, ...outer, anyOf: undefined, type: base.type, enum: base.enum ?? outer.enum };
    return {
      name,
      label: outer.title ?? humanize(name),
      description: outer.description,
      kind: kindOf(node),
      required: required.has(name),
      nullable,
      options: node.enum?.map(String),
      optionLabels: outer["x-labels"],
      tools: outer["x-tools"],
      min: node.minimum,
      max: node.maximum,
      maxItems: node.maxItems,
      default: outer.default,
    };
  });
}

export function initialValues(fields: FormField[]): FormValues {
  const values: FormValues = {};
  for (const f of fields) {
    if (f.kind === "boolean") values[f.name] = Boolean(f.default);
    else if (f.kind === "list") values[f.name] = Array.isArray(f.default) ? f.default.join("\n") : "";
    else if (f.kind === "select") values[f.name] = String(f.default ?? f.options?.[0] ?? "");
    else values[f.name] = f.default == null ? "" : String(f.default);
  }
  return values;
}

/** Form values -> tool inputs. Empty optional fields are left out so Python's defaults apply. */
export function toInputs(fields: FormField[], values: FormValues): Record<string, unknown> {
  const inputs: Record<string, unknown> = {};
  for (const f of fields) {
    const value = values[f.name];
    if (f.kind === "boolean") {
      inputs[f.name] = Boolean(value);
      continue;
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (f.kind === "list") {
      inputs[f.name] = text.split("\n").map((line) => line.trim()).filter(Boolean);
    } else if (text === "") {
      if (f.nullable) inputs[f.name] = null;
      else if (f.required) inputs[f.name] = ""; // let the API say what's missing
    } else if (f.kind === "integer" || f.kind === "number") {
      inputs[f.name] = Number(text);
    } else {
      inputs[f.name] = text;
    }
  }
  return inputs;
}
