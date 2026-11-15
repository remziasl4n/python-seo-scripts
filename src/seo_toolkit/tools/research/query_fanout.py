"""The searches Google's AI would run to answer a query, and which of them are real.

**How it works**

1. **Generate.** Gemini writes queries for each fan-out type: *related*, *implicit*,
   *comparative*, *reformulation*, *entity_expanded* (broader, narrower, part-of entities,
   labelled with the lexical relation) and *template* (what is / how to / cost / vs …).
   Your site's source context is in the prompt, so queries fit what the site is for.
2. **Observe.** A grounded Gemini call answers the seed using Google Search and records
   the searches it actually ran. Google says AI Mode works by "issuing multiple related
   searches across subtopics", so these are real fan-out, not guesses.
3. **Verify.** Each query is checked against Google autocomplete: *exact* means people
   type that query; *prefix* means people type longer searches that start with it.
4. **Flag rewordings.** Embeddings mark queries that are near-identical to a better-evidenced
   one in **near_duplicate_of**. Nothing is deleted.

**Evidence** sorts the table: *observed* (Gemini really searched it, or it's an exact
autocomplete match), *partial* (autocomplete prefix) and *model only* (Gemini's suggestion
with no outside confirmation). See docs/semantic-seo-principles.md, sections 1.3 and 3.

The prompt is in src/seo_toolkit/prompts/research/query_fanout.md: edit it to change what's asked.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from seo_toolkit.core.prompts import render
from seo_toolkit.tools.base import RunContext, Tool, ToolResult

FanoutType = Literal[
    "related", "implicit", "comparative", "reformulation", "entity_expanded", "template"
]
Intent = Literal["informational", "commercial", "transactional", "navigational"]
LexicalRelation = Literal[
    "none", "synonym", "hypernym", "hyponym", "meronym", "holonym", "related_entity"
]
Evidence = Literal["observed", "partial", "model only"]
EVIDENCE_ORDER: dict[str, int] = {"observed": 0, "partial": 1, "model only": 2}

# Cosine similarity above which two queries are flagged as rewordings of each other
NEAR_DUPLICATE = 0.96

COLUMNS = [
    "query",
    "evidence",
    "fanout_type",
    "intent",
    "entity",
    "attribute",
    "lexical_relation",
    "autocomplete",
    "sources",
    "near_duplicate_of",
    "rationale",
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
        title="Seed query or entity",
        description="E.g. 'inground pool cost' or 'fiberglass pool'.",
    )
    per_type: int = Field(
        6, ge=2, le=15, title="Queries per fan-out type", description="Six types, so 6 → ~36."
    )
    grounded: bool = Field(
        True,
        title="Record Gemini's real searches",
        description="One grounded call. Free for the first 5,000 searches a month.",
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
        return "observed"
    if autocomplete == "prefix":
        return "partial"
    return "model only"


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
    title = "Query fan-out"
    summary = "The searches Google's AI would run for a query, checked against real search data."
    needs = ("gemini_api_key",)
    Inputs = QueryFanoutInputs

    def run(self, inputs: QueryFanoutInputs, ctx: RunContext) -> ToolResult:
        site = ctx.site
        country = (inputs.country or site.country).lower()
        language = (inputs.language or site.language).lower()
        gemini = ctx.gemini
        notes: list[str] = []

        # 1. Generate
        ctx.progress(0.0, "Asking Gemini for fan-out queries…")
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
                "The site has no source_context, so queries aren't tailored to its purpose."
            )

        rows: dict[str, Row] = {}
        for item in generated:
            query = normalize(item.query)
            if query and query not in rows:
                rows[query] = Row(**{**item.model_dump(), "query": query}, sources={"gemini"})

        # 2. Observe
        if inputs.grounded and gemini.grounding:
            ctx.progress(0.2, "Answering with Google Search to record real searches…")
            answer = gemini.ground(
                inputs.query,
                system=(
                    f"Answer this search fully for someone in country {country}, "
                    "covering every subtopic they would need."
                ),
            )
            for searched in answer.search_queries:
                query = normalize(searched)
                if query in rows:
                    rows[query].sources.add("gemini-search")
                elif query:
                    rows[query] = Row(query, "observed search", sources={"gemini-search"})
            domains = list(dict.fromkeys(s.domain for s in answer.sources if s.domain))
            if domains:
                notes.append(f"Gemini's grounded answer cited: {', '.join(domains[:10])}.")
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

        records = [
            {
                **asdict(row),
                "sources": ", ".join(sorted(row.sources)),
                "evidence": evidence_for(row.sources, row.autocomplete),
                "near_duplicate_of": "",
            }
            for row in rows.values()
        ]
        table = pd.DataFrame(records, columns=COLUMNS)
        table["_rank"] = table["evidence"].map(EVIDENCE_ORDER)
        table = (
            table.sort_values(["_rank", "fanout_type"], kind="stable")
            .drop(columns="_rank")
            .reset_index(drop=True)
        )

        # 4. Flag rewordings
        ctx.progress(0.95, "Flagging near-identical rewordings…")
        if len(table) > 1:
            vectors = gemini.embed(table["query"].tolist(), task="similarity")
            table["near_duplicate_of"] = flag_near_duplicates(table["query"].tolist(), vectors)
        ctx.progress(1.0, "Done")

        counts = table["evidence"].value_counts()
        metrics: dict[str, int | float | str] = {
            "Queries": len(table),
            "Observed": int(counts.get("observed", 0)),
            "Partial": int(counts.get("partial", 0)),
            "Model only": int(counts.get("model only", 0)),
            "Gemini searches": int((table["sources"].str.contains("gemini-search")).sum()),
        }
        return ToolResult(table[COLUMNS], metrics, notes)
