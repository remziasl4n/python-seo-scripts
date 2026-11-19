import re

import pytest
from pydantic import ValidationError

from fakes import DictAutocomplete, FakeGemini
from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.config import SiteConfig
from seo_toolkit.core.prompts import PromptError, render
from seo_toolkit.core.sites import create_site, load_site
from seo_toolkit.tools.base import RunContext, discover
from seo_toolkit.tools.research.query_fanout import (
    QueryFanout,
    QueryFanoutInputs,
    autocomplete_match,
    evidence_for,
    normalize,
    plain_evidence,
)


def generated(query, fanout_type="related", **extra):
    return {
        "query": query,
        "fanout_type": fanout_type,
        "intent": "informational",
        "entity": "inground pool",
        "attribute": "cost",
        "lexical_relation": "none",
        "rationale": "why",
        **extra,
    }


@pytest.fixture
def gemini():
    return FakeGemini(
        generated=[
            generated("inground pool cost texas"),
            generated("Fiberglass vs Concrete Pool?", "comparative"),
            generated("inground pool price", "reformulation"),
            generated("pool permit requirements", "implicit"),
            generated("inground pool cost texas", "template"),  # duplicate: dropped
        ],
        searches=("inground pool cost texas", "average cost of inground pool installation"),
        same_meaning=(("inground pool cost texas", "inground pool price"),),
    )


@pytest.fixture
def autocomplete():
    return DictAutocomplete(
        {
            "fiberglass vs concrete pool": [
                "fiberglass vs concrete pool",
                "fiberglass vs concrete pool cost",
            ],
            "pool permit requirements": ["pool permit requirements texas"],
        }
    )


@pytest.fixture
def ctx(settings, gemini, autocomplete):
    return RunContext(
        settings,
        load_site("example", settings),
        connectors={"gemini": gemini, "autocomplete": autocomplete},
    )


def run(ctx, **inputs):
    return QueryFanout().run(QueryFanoutInputs(query="inground pool cost", **inputs), ctx)


def rows(result):
    return {r["query"]: r for r in result.table.to_dict("records")}


# --- Helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("  Pool  Cost? ", "pool cost"), ('"pool cost"', "pool cost"), ("Pool cost!", "pool cost")],
)
def test_normalize(raw, clean):
    assert normalize(raw) == clean


def test_autocomplete_match():
    assert autocomplete_match("pool cost", ["Pool Cost", "pool cost texas"]) == "exact"
    assert autocomplete_match("pool cost", ["pool cost texas"]) == "prefix"
    assert autocomplete_match("pool cost", ["pool costume"]) == "none"  # not a word prefix


def test_evidence_levels():
    assert evidence_for({"gemini", "gemini-search"}, "none") == "confirmed"
    assert evidence_for({"gemini"}, "exact") == "confirmed"
    assert evidence_for({"gemini"}, "prefix") == "partly confirmed"
    assert evidence_for({"gemini"}, "not checked") == "Gemini only"


def test_older_runs_evidence_reads_as_plain_labels():
    assert plain_evidence("observed") == "confirmed"
    assert plain_evidence("model only") == "Gemini only"
    assert plain_evidence("confirmed") == "confirmed"


def test_seed_is_normalized_and_required():
    assert QueryFanoutInputs(query=" Inground Pool Cost? ").query == "inground pool cost"
    with pytest.raises(ValidationError):
        QueryFanoutInputs(query="")


# --- The tool ----------------------------------------------------------------------------


def test_registered_and_needs_gemini(settings):
    assert discover()["research/query-fanout"] is QueryFanout
    assert QueryFanout.missing(settings) == ["GEMINI_API_KEY"]


def test_prompt_carries_site_context_and_seed(ctx, gemini):
    run(ctx, per_type=4)
    prompt = gemini.prompts[0]
    assert '"inground pool cost"' in prompt
    assert "Acme Pools designs and installs" in prompt
    assert "Central entity: swimming pool (product)" in prompt
    assert "Write 4 queries for EACH fan-out type" in prompt
    assert "$" not in prompt  # every placeholder filled


def test_generated_and_searched_queries_merge(ctx):
    table = rows(run(ctx))
    assert len(table) == 5  # 4 distinct generated + 1 search-only
    merged = table["inground pool cost texas"]
    assert merged["found_by"] == "Gemini, Gemini's Google search"
    assert merged["evidence"] == "confirmed"
    searched = table["average cost of inground pool installation"]
    assert (searched["kind"], searched["found_by"]) == (
        "Google search by Gemini",
        "Gemini's Google search",
    )


def test_table_uses_plain_labels(ctx):
    table = rows(run(ctx))
    compare = table["fiberglass vs concrete pool"]
    assert compare["kind"] == "Comparison"
    assert compare["reader_wants"] == "Learn"
    assert (compare["topic"], compare["aspect"]) == ("inground pool", "cost")
    assert table["pool permit requirements"]["kind"] == "Follow-up question"


def test_autocomplete_sets_evidence(ctx):
    table = rows(run(ctx))
    assert table["fiberglass vs concrete pool"]["autocomplete"] == "Exact match"
    assert table["fiberglass vs concrete pool"]["evidence"] == "confirmed"
    assert table["pool permit requirements"]["autocomplete"] == "Longer searches start with it"
    assert table["pool permit requirements"]["evidence"] == "partly confirmed"
    assert table["inground pool price"]["evidence"] == "Gemini only"


def test_sorted_by_evidence(ctx):
    order = run(ctx).table["evidence"].tolist()
    ranks = {"confirmed": 0, "partly confirmed": 1, "Gemini only": 2}
    assert [ranks[e] for e in order] == sorted(ranks[e] for e in order)


def test_near_duplicates_flagged_not_removed(ctx):
    table = rows(run(ctx))
    assert table["inground pool price"]["same_as"] == "inground pool cost texas"
    assert table["inground pool cost texas"]["same_as"] == ""


def test_metrics_and_cited_domains(ctx):
    result = run(ctx)
    assert result.metrics["Searches"] == 5
    assert result.metrics["Confirmed"] == 3
    assert result.metrics["Google searches by Gemini"] == 2
    assert any("a.com, b.org" in n for n in result.notes)


def test_switches_skip_grounding_and_autocomplete(ctx, gemini, autocomplete):
    table = rows(run(ctx, grounded=False, check_autocomplete=False))
    assert gemini.ground_calls == []
    assert autocomplete.calls == []
    assert {r["autocomplete"] for r in table.values()} == {"Not checked"}
    assert {r["evidence"] for r in table.values()} == {"Gemini only"}


def test_grounding_turned_off_in_settings_adds_note(ctx, gemini):
    gemini.grounding = False
    result = run(ctx)
    assert gemini.ground_calls == []
    assert any("GEMINI_GROUNDING" in n for n in result.notes)


def test_missing_source_context_adds_note(settings, gemini, autocomplete):
    create_site(settings, SiteConfig(name="bare", domain="https://bare.com/"))
    ctx = RunContext(
        settings,
        load_site("bare", settings),
        connectors={"gemini": gemini, "autocomplete": autocomplete},
    )
    result = run(ctx)
    assert "(not set in the site file)" in gemini.prompts[0]
    assert any("Sites page" in n for n in result.notes)


def test_empty_generation_gives_empty_table(ctx, gemini):
    gemini.generated, gemini.searches = [], ()
    result = run(ctx)
    assert result.table.empty
    assert "evidence" in result.table.columns


# --- Prompts -----------------------------------------------------------------------------


def test_render_reports_missing_placeholder():
    with pytest.raises(PromptError, match=r"uses \$"):
        render("research/query_fanout", query="x")


def test_render_unknown_prompt():
    with pytest.raises(PromptError, match="No prompt file"):
        render("research/nope")


def test_nothing_the_user_sees_contains_jargon(ctx):
    result = run(ctx)
    schema = QueryFanoutInputs.model_json_schema()["properties"].values()
    shown = [
        *result.notes,
        *map(str, result.metrics),
        QueryFanout.title,
        QueryFanout.summary,
        QueryFanout.description(),
        *(f.get("title", "") + " " + f.get("description", "") for f in schema),
        " ".join(result.table.columns),
        result.table.drop(columns=["query", "topic", "aspect", "why", "same_as"]).to_csv(),
    ]
    text = "\n".join(shown).lower()
    assert [w for w in rules.JARGON if re.search(rf"\b{re.escape(w)}\b", text)] == []
