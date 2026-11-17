/**
 * The site form's state, and conversion to and from the API's SiteConfig. List fields
 * (brand terms, competitors, sitemaps) are edited as one item per line.
 */
import type { Section, SiteConfig } from "./api";

export interface SiteFormState {
  name: string;
  domain: string;
  country: string;
  language: string;
  source_context: string;
  central_entity: string;
  entity_type: string;
  sections: Section[];
  brand_terms: string;
  competitors: string;
  gsc_property: string;
  ga4_property_id: string;
  sitemaps: string;
}

export const LIST_FIELDS = ["brand_terms", "competitors", "sitemaps"] as const;

export function emptySite(): SiteFormState {
  return {
    name: "",
    domain: "https://",
    country: "us",
    language: "en",
    source_context: "",
    central_entity: "",
    entity_type: "",
    sections: [],
    brand_terms: "",
    competitors: "",
    gsc_property: "",
    ga4_property_id: "",
    sitemaps: "",
  };
}

export function toFormState(site: SiteConfig): SiteFormState {
  return {
    ...site,
    sections: site.sections.map((s) => ({ ...s })),
    brand_terms: site.brand_terms.join("\n"),
    competitors: site.competitors.join("\n"),
    sitemaps: site.sitemaps.join("\n"),
  };
}

const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/** Form state -> SiteConfig. Blank section rows are dropped; text is trimmed. */
export function toSiteConfig(state: SiteFormState): SiteConfig {
  return {
    name: state.name.trim().toLowerCase(),
    domain: state.domain.trim(),
    country: state.country.trim().toLowerCase(),
    language: state.language.trim().toLowerCase(),
    source_context: state.source_context.trim(),
    central_entity: state.central_entity.trim(),
    entity_type: state.entity_type.trim(),
    sections: state.sections
      .map((s) => ({ ...s, path: s.path.trim(), name: s.name.trim() }))
      .filter((s) => s.path || s.name),
    brand_terms: lines(state.brand_terms),
    competitors: lines(state.competitors),
    gsc_property: state.gsc_property.trim(),
    ga4_property_id: state.ga4_property_id.trim(),
    sitemaps: lines(state.sitemaps),
  };
}

/** A suggested site name from a domain: "https://www.acme-pools.com/" -> "acme-pools". */
export function nameFromDomain(domain: string): string {
  const host = domain.replace(/^https?:\/\//, "").replace(/^www\./, "").split(/[/:?#]/)[0] ?? "";
  const base = host.includes(".") ? host.slice(0, host.lastIndexOf(".")) : host;
  return base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}
