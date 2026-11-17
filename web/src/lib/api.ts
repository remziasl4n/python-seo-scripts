/**
 * Typed client for the Python API. Types come from src/lib/api/schema.d.ts, generated
 * from the API itself (`pnpm gen:api`), so a changed endpoint fails the type check.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./api/schema";

type Schemas = components["schemas"];
export type Run = Schemas["RunRecord"];
export type RunStatus = Run["status"];
export type Rows = Schemas["Rows"];
export type Column = Schemas["Column"];
export type ToolSummary = Schemas["ToolSummary"];
export type ToolDetail = Schemas["ToolDetail"];
export type Sites = Schemas["Sites"];
export type SiteSummary = Schemas["SiteSummary"];
export type SiteConfig = Schemas["SiteConfig"];
export type Section = Schemas["Section"];
export type Check = Schemas["Check"];

export interface FieldError {
  field: string;
  label: string;
  message: string;
}

/** An API failure with a message fit to show the user. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fieldErrors: FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Relative URLs: the Next.js server passes /api/* through to the Python API
export const api = createClient<paths>({ baseUrl: "" });

const API_DOWN =
  "Can't reach the API. Start everything with `uv run seo dev` (or `uv run seo api`).";

export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "detail" in body) {
    const { detail, errors } = body as { detail: unknown; errors?: FieldError[] };
    if (typeof detail === "string") return new ApiError(status, detail, errors ?? []);
    if (Array.isArray(detail)) {
      // FastAPI's own validation errors (a malformed request, not a tool's inputs)
      return new ApiError(status, detail.map((d) => d?.msg ?? String(d)).join("; "));
    }
  }
  // The Next.js proxy answers 500 with no JSON when the Python API isn't running
  if (status >= 500) return new ApiError(status, API_DOWN);
  return new ApiError(status, `Request failed (${status}).`);
}

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch {
    throw new ApiError(0, API_DOWN);
  }
  if (result.error !== undefined || result.data === undefined) {
    throw toApiError(result.response.status, result.error);
  }
  return result.data;
}

export function downloadUrl(runId: string, format: "csv" | "xlsx"): string {
  return `/api/runs/${encodeURIComponent(runId)}/download?format=${format}`;
}
