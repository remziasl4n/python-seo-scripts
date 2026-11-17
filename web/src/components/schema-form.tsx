"use client";

/** A tool's input form, built from its JSON Schema. No per-tool front-end code needed. */
import { Play } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";

import type { FieldError } from "@/lib/api";
import { fieldsFromSchema, type FormField, type FormValues, initialValues, toInputs } from "@/lib/schema-form";

import { Button } from "./ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "./ui/field";

function Control({
  field,
  value,
  error,
  disabled,
  onChange,
}: {
  field: FormField;
  value: string | boolean | undefined;
  error?: string;
  disabled?: boolean;
  onChange: (value: string | boolean) => void;
}) {
  const id = `field-${field.name}`;
  const common = { id, name: field.name, disabled, "aria-invalid": error ? true : undefined };

  if (field.kind === "boolean") {
    return (
      <div className="space-y-0.5">
        <label htmlFor={id} className="flex items-center gap-2 text-[12px]">
          <Checkbox {...common} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {field.label}
        </label>
        {error ? (
          <p className="pl-5.5 text-[11px] text-bad">{error}</p>
        ) : (
          field.description && <p className="pl-5.5 text-[11px] text-muted">{field.description}</p>
        )}
      </div>
    );
  }

  let control;
  if (field.kind === "select") {
    control = (
      <Select {...common} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {field.options?.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </Select>
    );
  } else if (field.kind === "list") {
    control = (
      <Textarea
        {...common}
        rows={4}
        value={String(value ?? "")}
        placeholder="One per line"
        onChange={(e) => onChange(e.target.value)}
      />
    );
  } else {
    const numeric = field.kind === "integer" || field.kind === "number";
    control = (
      <Input
        {...common}
        type={numeric ? "number" : "text"}
        min={field.min}
        max={field.max}
        step={field.kind === "integer" ? 1 : numeric ? "any" : undefined}
        value={String(value ?? "")}
        placeholder={field.nullable ? "Leave empty to use the default" : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <Field label={field.label} htmlFor={id} hint={field.description} error={error} required={field.required}>
      {control}
    </Field>
  );
}

export function SchemaForm({
  schema,
  disabled,
  submitting,
  fieldErrors = [],
  onSubmit,
}: {
  schema: Record<string, unknown>;
  disabled?: boolean;
  submitting?: boolean;
  fieldErrors?: FieldError[];
  onSubmit: (inputs: Record<string, unknown>, refresh: boolean) => void;
}) {
  const fields = useMemo(() => fieldsFromSchema(schema), [schema]);
  const [values, setValues] = useState<FormValues>(() => initialValues(fields));
  const [refresh, setRefresh] = useState(false);
  const errors = Object.fromEntries(fieldErrors.map((e) => [e.field, e.message]));

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(toInputs(fields, values), refresh);
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      {fields.map((field) => (
        <Control
          key={field.name}
          field={field}
          value={values[field.name]}
          error={errors[field.name]}
          disabled={disabled || submitting}
          onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
        />
      ))}
      <div className="flex items-center justify-between border-t border-border pt-3">
        <label
          className="flex items-center gap-1.5 text-[11.5px] text-muted"
          title="Fetch fresh data from the APIs instead of reusing stored responses"
        >
          <Checkbox checked={refresh} onChange={(e) => setRefresh(e.target.checked)} disabled={disabled} />
          Ignore cache
        </label>
        <Button type="submit" variant="primary" disabled={disabled || submitting}>
          <Play className="size-3" /> {submitting ? "Starting…" : "Run"}
        </Button>
      </div>
    </form>
  );
}
