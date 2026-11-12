"""Every Google autocomplete suggestion for your seed queries: what people actually type.

**How it works**

- Each seed is sent as it is, then with every letter a–z after it ("pool cost a",
  "pool cost b" …), with question words in front ("how pool cost", "why pool cost" …)
  and with comparison words after ("pool cost vs", "pool cost for" …).
- Suggestions are merged across all those variations. **times_seen** counts how many
  variations produced a suggestion, a rough sign of how central it is to the seed.
  **best_position** is its highest place in any suggestion list.
- Autocomplete is the cheapest real-demand signal there is, so other research tools use
  it to check queries a model suggested (docs/semantic-seo-principles.md, section 3).

Question and comparison words are English, so they're skipped for other languages.
A full run makes about 45 requests per seed; reruns come from the cache.
"""

from __future__ import annotations

from string import ascii_lowercase
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from seo_toolkit.tools.base import RunContext, Tool, ToolResult

QUESTION_WORDS = ("what", "how", "why", "when", "where", "which", "who", "can", "is", "are", "does")
COMPARISON_WORDS = ("vs", "for", "with", "without", "near", "or", "and")

Expansion = Literal["everything", "alphabet", "questions", "seed only"]
COLUMNS = [
    "seed",
    "suggestion",
    "times_seen",
    "best_position",
    "found_via",
    "variation_type",
    "words",
    "is_brand",
]


class AutocompleteInputs(BaseModel):
    seeds: list[str] = Field(
        min_length=1,
        max_length=20,
        title="Seed queries",
        description="One per line, up to 20. E.g. 'pool cost'.",
    )
    expand: Expansion = Field(
        "everything",
        title="Variations",
        description="Which variations of each seed to request.",
    )
    country: str | None = Field(
        None, description="Two-letter country code. Empty = the site's country."
    )
    language: str | None = Field(
        None, description="Two-letter language code. Empty = the site's language."
    )

    @field_validator("seeds")
    @classmethod
    def _clean_seeds(cls, seeds: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(s.strip().lower() for s in seeds if s.strip()))
        if not cleaned:
            raise ValueError("add at least one seed query")
        return cleaned


def variations(seed: str, expand: Expansion, english: bool) -> list[tuple[str, str]]:
    """(query, variation type) pairs to request for one seed."""
    queries = [(seed, "seed")]
    if expand in ("everything", "alphabet"):
        queries += [(f"{seed} {letter}", "alphabet") for letter in ascii_lowercase]
    if expand in ("everything", "questions") and english:
        queries += [(f"{word} {seed}", "question") for word in QUESTION_WORDS]
        queries += [(f"{seed} {word}", "comparison") for word in COMPARISON_WORDS]
    return queries


class Autocomplete(Tool):
    name = "autocomplete"
    group = "research"
    title = "Autocomplete"
    summary = (
        "Every Google autocomplete suggestion for your seeds, with a–z and question variations."
    )
    Inputs = AutocompleteInputs

    def run(self, inputs: AutocompleteInputs, ctx: RunContext) -> ToolResult:
        country = (inputs.country or ctx.site.country).lower()
        language = (inputs.language or ctx.site.language).lower()
        english = language == "en"
        client = ctx.autocomplete
        requests_before, cached_before = client.requests, client.cached

        jobs = [
            (seed, query, kind)
            for seed in inputs.seeds
            for query, kind in variations(seed, inputs.expand, english)
        ]
        rows = []
        for done, (seed, query, kind) in enumerate(jobs):
            ctx.progress(done / len(jobs), f"Asking Google for “{query}”")
            for position, suggestion in enumerate(client.suggest(query, country, language), 1):
                rows.append(
                    {
                        "seed": seed,
                        "suggestion": suggestion.strip().lower(),
                        "position": position,
                        "found_via": query,
                        "variation_type": kind,
                    }
                )
        ctx.progress(1.0, "Done")

        table = self._merge(pd.DataFrame(rows), ctx)
        notes = []
        if not english and inputs.expand in ("everything", "questions"):
            notes.append(
                "Question and comparison variations were skipped: they only exist in English."
            )
        metrics: dict[str, int | float | str] = {
            "Suggestions": len(table),
            "Seeds": len(inputs.seeds),
            "Requests to Google": client.requests - requests_before,
            "From cache": client.cached - cached_before,
        }
        return ToolResult(table, metrics, notes)

    @staticmethod
    def _merge(raw: pd.DataFrame, ctx: RunContext) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(columns=COLUMNS)
        # The first row for a suggestion is where it was first found (seed before a–z, etc.)
        table = (
            raw.groupby(["seed", "suggestion"], sort=False)
            .agg(
                times_seen=("found_via", "nunique"),
                best_position=("position", "min"),
                found_via=("found_via", "first"),
                variation_type=("variation_type", "first"),
            )
            .reset_index()
        )
        table["words"] = table["suggestion"].map(lambda s: len(s.split()))
        table["is_brand"] = table["suggestion"].map(ctx.site.is_brand)
        table = table.sort_values(
            ["seed", "times_seen", "best_position"], ascending=[True, False, True], kind="stable"
        )
        return table[COLUMNS].reset_index(drop=True)
