import { describe, expect, it } from "vitest";

import type { SiteConfig } from "./api";
import { emptySite, nameFromDomain, toFormState, toSiteConfig } from "./site-form";

const site: SiteConfig = {
  name: "acme",
  domain: "https://acme.com/",
  country: "us",
  language: "en",
  source_context: "We sell anvils.",
  central_entity: "anvil",
  entity_type: "product",
  sections: [{ path: "/anvils/", name: "Anvils", role: "core" }],
  brand_terms: ["acme", "acme anvils"],
  competitors: [],
  gsc_property: "",
  ga4_property_id: "",
  sitemaps: ["https://acme.com/sitemap.xml"],
};

describe("site form", () => {
  it("round-trips a site through the form", () => {
    expect(toSiteConfig(toFormState(site))).toEqual(site);
  });

  it("edits lists one item per line and cleans up input", () => {
    const state = {
      ...toFormState(site),
      name: " Acme ",
      country: "US",
      brand_terms: "acme\n\n  acme anvils  \n",
      sections: [...site.sections, { path: "", name: "", role: "outer" as const }],
    };
    const config = toSiteConfig(state);
    expect(config.name).toBe("acme");
    expect(config.country).toBe("us");
    expect(config.brand_terms).toEqual(["acme", "acme anvils"]);
    expect(config.sections).toHaveLength(1); // the blank row is dropped
  });

  it("starts new sites with sensible defaults", () => {
    expect(emptySite()).toMatchObject({ country: "us", language: "en", sections: [] });
  });
});

describe("nameFromDomain", () => {
  it.each([
    ["https://www.acme-pools.com/", "acme-pools"],
    ["http://shop.example.co.uk/path", "shop-example-co"],
    ["acme.com", "acme"],
    ["https://", ""],
  ])("%s -> %s", (domain, name) => {
    expect(nameFromDomain(domain)).toBe(name);
  });
});
