import pytest
from pydantic import ValidationError

from fakes import DictAutocomplete, FakeGemini
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
    assert evidence_for({"gemini", "gemini-search"}, "none") == "observed"
    assert evidence_for({"gemini"}, "exact") == "observed"
    assert evidence_for({"gemini"}, "prefix") == "partial"
    assert evidence_for({"gemini"}, "not checked") == "model only"


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
    assert merged["sources"] == "gemini, gemini-search"
    assert merged["evidence"] == "observed"
    searched = table["average cost of inground pool installation"]
    assert (searched["fanout_type"], searched["sources"]) == ("observed search", "gemini-search")


def test_autocomplete_sets_evidence(ctx):
    table = rows(run(ctx))
    assert table["fiberglass vs concrete pool"]["autocomplete"] == "exact"
    assert table["fiberglass vs concrete pool"]["evidence"] == "observed"
    assert table["pool permit requirements"]["autocomplete"] == "prefix"
    assert table["pool permit requirements"]["evidence"] == "partial"
    assert table["inground pool price"]["evidence"] == "model only"


def test_sorted_by_evidence(ctx):
    order = run(ctx).table["evidence"].tolist()
    ranks = {"observed": 0, "partial": 1, "model only": 2}
    assert [ranks[e] for e in order] == sorted(ranks[e] for e in order)


def test_near_duplicates_flagged_not_removed(ctx):
    table = rows(run(ctx))
    assert table["inground pool price"]["near_duplicate_of"] == "inground pool cost texas"
    assert table["inground pool cost texas"]["near_duplicate_of"] == ""


def test_metrics_and_cited_domains(ctx):
    result = run(ctx)
    assert result.metrics["Queries"] == 5
    assert result.metrics["Observed"] == 3
    assert result.metrics["Gemini searches"] == 2
    assert any("a.com, b.org" in n for n in result.notes)


def test_switches_skip_grounding_and_autocomplete(ctx, gemini, autocomplete):
    table = rows(run(ctx, grounded=False, check_autocomplete=False))
    assert gemini.ground_calls == []
    assert autocomplete.calls == []
    assert {r["autocomplete"] for r in table.values()} == {"not checked"}
    assert {r["evidence"] for r in table.values()} == {"model only"}


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
    assert any("no source_context" in n for n in result.notes)


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
