"""The searches people (and Google's AI) run around a topic, and which of them are real.

**How it works**

1. **Suggest.** Gemini lists the searches someone researching your topic would also run,
   in six kinds: *related topics*, *follow-up questions* (needs they didn't say out loud),
   *comparisons*, *the same search in other words*, *broader or narrower* versions, and
   *common questions* (what is, how to, cost, types of …). Your site's description is
   included, so the searches fit what your site is for.
2. **Watch Google's AI.** Gemini answers your search using Google Search, and records the
   searches it actually ran. Google's AI answers work this way, so these are real.
3. **Check autocomplete.** Each search is looked up in Google's autocomplete: an *exact
   match* means people type it; *longer searches start with it* means people type longer
   versions.
4. **Spot rewordings.** Searches that mean the same as a better-supported one are marked
   in **same_as**. Nothing is deleted.

**Evidence** sorts the table: *confirmed* (Gemini really searched it, or people type it),
*partly confirmed* (people type longer versions) and *Gemini only* (a suggestion nothing
else backs up).

The prompt is in src/seo_toolkit/prompts/research/query_fanout.md: edit it to change what's asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.prompts import render
from seo_toolkit.tools.base import RunContext, Tool, ToolResult

FanoutType = Literal[
    "related", "implicit", "comparative", "reformulation", "entity_expanded", "template"
]
Intent = Literal["informational", "commercial", "transactional", "navigational"]
LexicalRelation = Literal[
    "none", "synonym", "hypernym", "hyponym", "meronym", "holonym", "related_entity"
]
Evidence = Literal["confirmed", "partly confirmed", "Gemini only"]
CONFIRMED: Evidence = "confirmed"
PARTLY: Evidence = "partly confirmed"
GEMINI_ONLY: Evidence = "Gemini only"
EVIDENCE_ORDER: dict[str, int] = {CONFIRMED: 0, PARTLY: 1, GEMINI_ONLY: 2}
# Runs saved before the plain-English labels
LEGACY_EVIDENCE = {"observed": CONFIRMED, "partial": PARTLY, "model only": GEMINI_ONLY}

# What the table shows instead of the internal names Gemini answers with
KIND_LABELS = {
    "related": "Related topic",
    "implicit": "Follow-up question",
    "comparative": "Comparison",
    "reformulation": "Same search, other words",
    "entity_expanded": "Broader or narrower",
    "template": "Common question",
    "observed search": "Google search by Gemini",
}
READER_WANTS = {
    intent: rules.INTENTS[guide].label for intent, guide in rules.SEARCH_INTENTS.items()
}
RELATION_LABELS = {
    "none": "",
    "synonym": "Same meaning",
    "hypernym": "Broader",
    "hyponym": "Narrower",
    "meronym": "A part of it",
    "holonym": "What it's part of",
    "related_entity": "Related",
}
AUTOCOMPLETE_LABELS = {
    "exact": "Exact match",
    "prefix": "Longer searches start with it",
    "none": "No",
    "not checked": "Not checked",
}
SOURCE_LABELS = {
    "gemini": "Gemini",
    "gemini-search": "Gemini's Google search",
    "autocomplete": "Autocomplete",
}

# Cosine similarity above which two queries are flagged as rewordings of each other
NEAR_DUPLICATE = 0.96

COLUMNS = [
    "query",
    "evidence",
    "kind",
    "reader_wants",
    "topic",
    "aspect",
    "relation",
    "autocomplete",
    "found_by",
    "same_as",
    "why",
]


class FanoutQuery(BaseModel):
    query: str
    fanout_type: FanoutType
    intent: Intent
    entity: str
    attribute: str = Field(description="Aspect of the entity, e.g. cost. Empty if none.")
    lexical_relation: LexicalRelation
    rationale: str


class FanoutQueries(BaseModel):
    queries: list[FanoutQuery]


class QueryFanoutInputs(BaseModel):
    query: str = Field(
        min_length=2,
        title="Search or topic",
        description="E.g. 'inground pool cost' or 'fiberglass pool'.",
    )
    per_type: int = Field(
        6, ge=2, le=15, title="Searches per kind", description="Six kinds, so 6 gives about 36."
    )
    grounded: bool = Field(
        True,
        title="Record Gemini's real Google searches",
        description="One Gemini answer using Google Search. The first 5,000 a month are free.",
    )
    check_autocomplete: bool = Field(
        True,
        title="Check against autocomplete",
        description="One autocomplete request per query (cached).",
    )
    country: str | None = Field(None, description="Two-letter code. Empty = the site's country.")
    language: str | None = Field(None, description="Two-letter code. Empty = the site's language.")

    @field_validator("query")
    @classmethod
    def _clean(cls, value: str) -> str:
        return normalize(value)


@dataclass
class Row:
    query: str
    fanout_type: str
    intent: str = ""
    entity: str = ""
    attribute: str = ""
    lexical_relation: str = ""
    rationale: str = ""
    sources: set[str] = field(default_factory=set)
    autocomplete: str = "not checked"


def normalize(query: str) -> str:
    """Lowercase, single spaces, no surrounding punctuation: how queries are compared."""
    return re.sub(r"\s+", " ", query.lower()).strip(" ?.!,;:\"'")


def autocomplete_match(query: str, suggestions: list[str]) -> str:
    normalized = {normalize(s) for s in suggestions}
    if query in normalized:
        return "exact"
    if any(s.startswith(query + " ") for s in normalized):
        return "prefix"
    return "none"


def evidence_for(sources: set[str], autocomplete: str) -> Evidence:
    if "gemini-search" in sources or autocomplete == "exact":
        return CONFIRMED
    if autocomplete == "prefix":
        return PARTLY
    return GEMINI_ONLY


def plain_evidence(value: str) -> str:
    """Evidence as the table shows it, including from runs saved with the older labels."""
    return LEGACY_EVIDENCE.get(value, value)


def grounding_system(country: str) -> str:
    """The instruction for the grounded answer. Shared, so other tools reuse its cache."""
    return (
        f"Answer this search fully for someone in country {country}, "
        "covering every subtopic they would need."
    )


def flag_near_duplicates(queries: list[str], vectors: np.ndarray) -> list[str]:
    """For each query, the earlier (better-evidenced) query it nearly repeats, or ''."""
    similarity = vectors @ vectors.T
    flags = []
    for i in range(len(queries)):
        earlier = [j for j in range(i) if similarity[i, j] >= NEAR_DUPLICATE]
        flags.append(queries[earlier[0]] if earlier else "")
    return flags


class QueryFanout(Tool):
    name = "query-fanout"
    group = "research"
    title = "Related searches"
    summary = "The searches Google's AI runs to answer a query, checked against real search data."
    needs = ("gemini_api_key",)
    Inputs = QueryFanoutInputs

    def run(self, inputs: QueryFanoutInputs, ctx: RunContext) -> ToolResult:
        site = ctx.site
        country = (inputs.country or site.country).lower()
        language = (inputs.language or site.language).lower()
        gemini = ctx.gemini
        notes: list[str] = []

        # 1. Generate
        ctx.progress(0.0, "Asking Gemini for related searches…")
        prompt = render(
            "research/query_fanout",
            domain=site.domain,
            source_context=site.source_context.strip() or "(not set in the site file)",
            central_entity=site.central_entity or "(not set)",
            entity_type=site.entity_type or "entity",
            country=country,
            language=language,
            query=inputs.query,
            per_type=inputs.per_type,
        )
        generated = gemini.generate_json(prompt, FanoutQueries).queries
        if not site.source_context.strip():
            notes.append(
                "Your site has no description yet, so searches aren't tailored to what you "
                "sell. Add one on the Sites page."
            )

        rows: dict[str, Row] = {}
        for item in generated:
            query = normalize(item.query)
            if query and query not in rows:
                rows[query] = Row(**{**item.model_dump(), "query": query}, sources={"gemini"})

        # 2. Observe
        if inputs.grounded and gemini.grounding:
            ctx.progress(0.2, "Answering with Google Search to record the real searches…")
            answer = gemini.ground(inputs.query, system=grounding_system(country))
            for searched in answer.search_queries:
                query = normalize(searched)
                if query in rows:
                    rows[query].sources.add("gemini-search")
                elif query:
                    rows[query] = Row(query, "observed search", sources={"gemini-search"})
            domains = list(dict.fromkeys(s.domain for s in answer.sources if s.domain))
            if domains:
                notes.append(
                    f"Gemini's answer (using Google Search) cited: {', '.join(domains[:10])}."
                )
        elif inputs.grounded:
            notes.append(
                "Grounding is off (GEMINI_GROUNDING=false), so no real searches were recorded."
            )

        # 3. Verify
        queries = list(rows)
        if inputs.check_autocomplete:
            client = ctx.autocomplete
            for done, query in enumerate(queries):
                ctx.progress(0.3 + 0.65 * done / len(queries), f"Checking autocomplete: “{query}”")
                match = autocomplete_match(query, client.suggest(query, country, language))
                rows[query].autocomplete = match
                if match != "none":
                    rows[query].sources.add("autocomplete")

        records = [self._record(row) for row in rows.values()]
        table = pd.DataFrame(records, columns=COLUMNS)
        table["_rank"] = table["evidence"].map(EVIDENCE_ORDER)
        table = (
            table.sort_values(["_rank", "kind"], kind="stable")
            .drop(columns="_rank")
            .reset_index(drop=True)
        )

        # 4. Spot rewordings
        ctx.progress(0.95, "Spotting searches that mean the same thing…")
        if len(table) > 1:
            vectors = gemini.embed(table["query"].tolist(), task="similarity")
            table["same_as"] = flag_near_duplicates(table["query"].tolist(), vectors)
        ctx.progress(1.0, "Done")

        counts = table["evidence"].value_counts()
        searched = SOURCE_LABELS["gemini-search"]
        metrics: dict[str, int | float | str] = {
            "Searches": len(table),
            "Confirmed": int(counts.get(CONFIRMED, 0)),
            "Partly confirmed": int(counts.get(PARTLY, 0)),
            "Gemini only": int(counts.get(GEMINI_ONLY, 0)),
            "Google searches by Gemini": int(table["found_by"].str.contains(searched).sum()),
        }
        return ToolResult(table[COLUMNS], metrics, notes)

    @staticmethod
    def _record(row: Row) -> dict[str, str]:
        """A row as the table shows it: plain labels instead of Gemini's internal names."""
        return {
            "query": row.query,
            "evidence": evidence_for(row.sources, row.autocomplete),
            "kind": KIND_LABELS.get(row.fanout_type, row.fanout_type),
            "reader_wants": READER_WANTS.get(row.intent, ""),
            "topic": row.entity,
            "aspect": row.attribute,
            "relation": RELATION_LABELS.get(row.lexical_relation, ""),
            "autocomplete": AUTOCOMPLETE_LABELS[row.autocomplete],
            "found_by": ", ".join(SOURCE_LABELS[s] for s in sorted(row.sources)),
            "same_as": "",
            "why": row.rationale,
        }
