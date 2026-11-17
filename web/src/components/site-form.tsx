"use client";

/** Create or edit a site. Short explanations sit next to the semantic SEO fields. */
import { Plus, Save, X } from "lucide-react";
import { type FormEvent, useState } from "react";

import type { FieldError, SiteConfig } from "@/lib/api";
import { nameFromDomain, type SiteFormState, toSiteConfig } from "@/lib/site-form";

import { Button } from "./ui/button";
import { Field, Input, Select, Textarea } from "./ui/field";
import { Callout, Panel } from "./ui/panel";

export function SiteForm({
  initial,
  isNew,
  saving,
  fieldErrors = [],
  onSubmit,
  extraActions,
}: {
  initial: SiteFormState;
  isNew: boolean;
  saving: boolean;
  fieldErrors?: FieldError[];
  onSubmit: (site: SiteConfig) => void;
  extraActions?: React.ReactNode;
}) {
  const [state, setState] = useState(initial);
  const [nameTouched, setNameTouched] = useState(!isNew);
  const errors = Object.fromEntries(fieldErrors.map((e) => [e.field, e.message]));
  const sectionErrors = fieldErrors.filter((e) => e.field.startsWith("sections."));

  function set<K extends keyof SiteFormState>(key: K, value: SiteFormState[K]) {
    setState((current) => ({ ...current, [key]: value }));
  }

  function setDomain(domain: string) {
    // Suggest a name from the domain until the user types their own
    setState((current) => ({
      ...current,
      domain,
      name: nameTouched ? current.name : nameFromDomain(domain),
    }));
  }

  function setSection(index: number, key: "path" | "name" | "role", value: string) {
    setState((current) => ({
      ...current,
      sections: current.sections.map((s, i) => (i === index ? { ...s, [key]: value } : s)),
    }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(toSiteConfig(state));
  }

  const text = (key: keyof SiteFormState, label: string, hint?: string, props: object = {}) => (
    <Field label={label} htmlFor={`site-${key}`} hint={hint} error={errors[key]}>
      <Input
        id={`site-${key}`}
        value={String(state[key])}
        onChange={(e) => set(key, e.target.value as never)}
        aria-invalid={errors[key] ? true : undefined}
        {...props}
      />
    </Field>
  );

  const list = (key: "brand_terms" | "competitors" | "sitemaps", label: string, hint: string) => (
    <Field label={label} htmlFor={`site-${key}`} hint={hint} error={errors[key]}>
      <Textarea
        id={`site-${key}`}
        rows={3}
        value={state[key]}
        placeholder="One per line"
        onChange={(e) => set(key, e.target.value)}
      />
    </Field>
  );

  return (
    <form onSubmit={submit} className="grid gap-4 xl:grid-cols-2" noValidate>
      <Panel title="Basics">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label="Domain" htmlFor="site-domain" hint="Full URL, e.g. https://www.example.com/" error={errors.domain} required>
              <Input id="site-domain" value={state.domain} onChange={(e) => setDomain(e.target.value)} aria-invalid={errors.domain ? true : undefined} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field
              label="Name"
              htmlFor="site-name"
              required
              error={errors.name}
              hint={isNew ? "Short id for links and run history: lowercase letters, numbers and dashes." : "A site's name can't be changed."}
            >
              <Input
                id="site-name"
                value={state.name}
                disabled={!isNew}
                onChange={(e) => {
                  setNameTouched(true);
                  set("name", e.target.value);
                }}
                aria-invalid={errors.name ? true : undefined}
              />
            </Field>
          </div>
          {text("country", "Country", "Two-letter code, e.g. us", { maxLength: 2 })}
          {text("language", "Language", "Two-letter code, e.g. en", { maxLength: 2 })}
        </div>
      </Panel>

      <Panel title="Semantic context">
        <div className="space-y-3">
          <Field
            label="Source context"
            htmlFor="site-source_context"
            error={errors.source_context}
            hint="Why the site exists and how it makes money. Tools use it to decide which topics fit the site and which to leave out."
          >
            <Textarea id="site-source_context" rows={3} value={state.source_context} onChange={(e) => set("source_context", e.target.value)} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            {text("central_entity", "Central entity", "The thing every section of the site is about")}
            {text("entity_type", "Entity type", "e.g. product, service, place")}
          </div>
        </div>
      </Panel>

      <Panel
        title="Sections"
        className="xl:col-span-2"
        actions={
          <Button type="button" onClick={() => set("sections", [...state.sections, { path: "/", name: "", role: "outer" }])}>
            <Plus className="size-3" /> Add section
          </Button>
        }
      >
        <p className="mb-2 text-[11.5px] text-muted">
          Parts of the site and their role in the topical map. <b>Core</b> sections cover the central entity&apos;s
          main attribute (what the site sells); <b>outer</b> sections cover supporting topics that build trust.
        </p>
        {state.sections.length === 0 ? (
          <p className="py-2 text-[12px] text-muted">No sections yet.</p>
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="pb-1 font-semibold">Path</th>
                <th className="pb-1 pl-2 font-semibold">Name</th>
                <th className="w-28 pb-1 pl-2 font-semibold">Role</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {state.sections.map((section, i) => (
                <tr key={i}>
                  <td className="py-0.5">
                    <Input aria-label={`Section ${i + 1} path`} value={section.path} onChange={(e) => setSection(i, "path", e.target.value)} aria-invalid={errors[`sections.${i}.path`] ? true : undefined} className="font-mono" />
                  </td>
                  <td className="py-0.5 pl-2">
                    <Input aria-label={`Section ${i + 1} name`} value={section.name} onChange={(e) => setSection(i, "name", e.target.value)} aria-invalid={errors[`sections.${i}.name`] ? true : undefined} />
                  </td>
                  <td className="py-0.5 pl-2">
                    <Select aria-label={`Section ${i + 1} role`} value={section.role} onChange={(e) => setSection(i, "role", e.target.value)}>
                      <option value="core">core</option>
                      <option value="outer">outer</option>
                    </Select>
                  </td>
                  <td className="py-0.5 pl-1">
                    <Button type="button" variant="ghost" aria-label={`Remove section ${i + 1}`} onClick={() => set("sections", state.sections.filter((_, j) => j !== i))}>
                      <X className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {sectionErrors.length > 0 && (
          <div className="mt-2">
            <Callout tone="bad">{sectionErrors.map((e) => `${e.label}: ${e.message}`).join("\n")}</Callout>
          </div>
        )}
      </Panel>

      <Panel title="Brand and competitors">
        <div className="space-y-3">
          {list("brand_terms", "Brand terms", "Queries containing these count as branded")}
          {list("competitors", "Competitors", "Competitor site URLs")}
        </div>
      </Panel>

      <Panel title="Data sources">
        <div className="space-y-3">
          {text("gsc_property", "Search Console property", "sc-domain:example.com, or the full URL prefix")}
          {text("ga4_property_id", "GA4 property ID", "Numeric. Optional")}
          {list("sitemaps", "Sitemaps", "Sitemap URLs")}
        </div>
      </Panel>

      <div className="flex items-center gap-2 xl:col-span-2">
        <Button type="submit" variant="primary" disabled={saving}>
          <Save className="size-3" /> {saving ? "Saving…" : isNew ? "Create site" : "Save changes"}
        </Button>
        {extraActions}
      </div>
    </form>
  );
}
