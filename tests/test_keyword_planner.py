import re

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from fakes import FakeGemini
from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.config import SiteConfig
from seo_toolkit.core.sites import create_site, load_site
from seo_toolkit.tools.base import RunContext, discover
from seo_toolkit.tools.planning.keyword_planner import (
    KeywordPlanner,
    KeywordPlannerInputs,
    build_pages,
    comparable,
    group_keywords,
    rank_pages,
)

# Three topics a pool installer might see; keywords in a tuple mean the same thing
COST = ("inground pool cost", "how much does an inground pool cost", "inground pool price")
PERMITS = ("pool permit texas", "do i need a permit for a pool")
COMPARE = ("fiberglass vs concrete pool", "concrete or fiberglass pool")
LONE = "pool heater noise"
KEYWORDS = [*COST, *PERMITS, *COMPARE, LONE, "pool lights", "pool fence rules"]


def plans_from_prompt(prompt: str) -> dict:
    """Answer like Gemini would: a plan per page listed in the prompt, all keywords as headings."""
    pages = []
    for number, main, others in re.findall(
        r'- page (\d+): main keyword "([^"]+)"; other keywords: (.*)', prompt
    ):
        keywords = re.findall(r'"([^"]+)"', others)
        intent = "compare" if " vs " in main or " or " in main else "learn"
        pages.append(
            {
                "page": int(number),
                "page_name": main.title(),
                "intent": intent,
                "page_type": "comparison" if intent == "compare" else "guide",
                "section": "/cost/" if "cost" in main else "/nowhere/",
                "url_slug": main,
                "title": main.capitalize(),
                "h1": f"{main.capitalize()}: the full guide",
                "meta_description": f"Everything about {main}.",
                "keywords": [
                    {"keyword": k, "use_as": "heading", "heading": f"What about {k}?"}
                    for k in keywords[:-1]  # leave one out: the tool must still place it
                ],
            }
        )
    return {"pages": pages}


@pytest.fixture
def gemini():
    fake = FakeGemini(same_meaning=(COST, PERMITS, COMPARE))
    fake.answers["PagePlans"] = plans_from_prompt
    return fake


@pytest.fixture
def ctx(settings, gemini):
    return RunContext(settings, load_site("example", settings), connectors={"gemini": gemini})


def run(ctx, **inputs):
    return KeywordPlanner().run(KeywordPlannerInputs(**{"keywords": KEYWORDS, **inputs}), ctx)


# --- Inputs --------------------------------------------------------------------------


def test_needs_keywords_or_a_previous_run():
    with pytest.raises(ValidationError, match="add keywords above, or pick a previous run"):
        KeywordPlannerInputs(keywords=[" ", ""])
    assert KeywordPlannerInputs(from_run="20261117-100000-abcdef").keywords == []


def test_keywords_are_cleaned_and_deduplicated():
    inputs = KeywordPlannerInputs(keywords=["  Pool   Cost ", "pool cost", "Pool Permit"])
    assert inputs.keywords == ["pool cost", "pool permit"]


def test_form_shows_friendly_choices():
    schema = KeywordPlannerInputs.model_json_schema()["properties"]
    assert schema["split"]["x-labels"]["broad"] == "Fewer, broader pages"
    assert schema["from_run"]["x-widget"] == "run"


# --- Grouping ------------------------------------------------------------------------


def blobs(sizes: list[int], dims: int = 32, spread: float = 0.05, seed: int = 0) -> np.ndarray:
    """Points in tight groups around shared directions, all sharing a common 'topic' vector."""
    rng = np.random.default_rng(seed)
    topic = rng.normal(size=dims) * 4  # what every keyword in the list has in common
    rows = []
    for size in sizes:
        centre = rng.normal(size=dims)
        rows += [topic + centre + rng.normal(scale=spread, size=dims) for _ in range(size)]
    return np.array(rows)


def test_groups_are_found_despite_a_shared_topic():
    labels = group_keywords(blobs([4, 3, 5, 2]), "balanced")
    assert [len(set(labels[a:b])) for a, b in [(0, 4), (4, 7), (7, 12), (12, 14)]] == [1, 1, 1, 1]
    assert len(set(labels)) == 4


def test_oversized_groups_are_split_again():
    # 40 keywords that look like one topic next to an outlier, but are two topics inside
    vectors = np.vstack([blobs([20, 20], spread=0.3, seed=5), blobs([1], seed=6) * 20])
    labels = group_keywords(vectors, "broad")
    assert max(np.bincount(labels)) <= 30


def test_split_setting_changes_the_number_of_pages():
    vectors = blobs([6, 6, 6], spread=0.6, seed=2)
    counts = {s: len(set(group_keywords(vectors, s))) for s in ("broad", "balanced", "narrow")}
    assert counts["broad"] <= counts["balanced"] <= counts["narrow"]


def test_short_lists_use_plain_similarity():
    _, centred = comparable(blobs([2, 2]))
    assert not centred
    assert len(set(group_keywords(blobs([2, 2]), "balanced"))) == 2
    assert list(group_keywords(blobs([1]), "balanced")) == [0]


def test_main_keyword_prefers_real_searches_and_lone_keywords_become_sections():
    keywords = ["a b c", "a", "b", "lone", "searched lone"]
    vectors = blobs([3, 1, 1], seed=4)[:5]
    points, _ = comparable(vectors)
    groups = np.array([0, 0, 0, 1, 2])
    evidence = ["", "", "confirmed", "", "confirmed"]
    pages = build_pages(keywords, points, groups, evidence)
    assert len(pages) == 2  # "lone" folded in; "searched lone" really searched, so kept
    first = next(p for p in pages if 0 in p.members)
    assert first.folded == [3]
    assert keywords[first.main] == "b"  # confirmed beats slightly better fit


def test_core_pages_come_first():
    class Plan:
        def __init__(self, section, intent):
            self.section, self.intent = section, intent

    from seo_toolkit.tools.planning.keyword_planner import Page

    small_core = Page([0], plan=Plan("/cost/", "learn"))  # type: ignore[arg-type]
    big_outer = Page([1, 2, 3], plan=Plan("/guides/", "learn"))  # type: ignore[arg-type]
    pages = [big_outer, small_core]
    rank_pages(pages, ["", "", "", ""], {"/cost/"})
    assert pages[0] is small_core and small_core.priority == "Write first"


# --- The tool ------------------------------------------------------------------------


def test_registered_with_a_jargon_free_name(settings):
    tool = discover()["planning/keyword-planner"]
    assert tool.title == "Keyword planner"
    assert tool.missing(settings) == ["GEMINI_API_KEY"]


def test_one_page_per_search_with_roles(ctx):
    result = run(ctx)
    table = result.table
    pages = table.groupby("page")["keyword"].apply(set).to_dict()
    assert set(COST) in pages.values() or any(set(COST) <= v for v in pages.values())
    assert table["use_as"].value_counts()["Main keyword"] == table["page"].nunique()
    # Every keyword is placed exactly once
    assert sorted(table["keyword"]) == sorted(KEYWORDS)
    # The keyword Gemini left out is still placed, as a mention or a heading
    assert set(table["use_as"]) <= {"Main keyword", "Heading", "In the text"}
    assert result.metrics["Keywords"] == len(KEYWORDS)


def test_where_to_use_each_keyword_is_spelled_out(ctx):
    table = run(ctx).table
    main = table[table["use_as"] == "Main keyword"].iloc[0]
    assert "Title" in main["where_to_use_it"] and "H1" in main["where_to_use_it"]
    heading = table[table["use_as"] == "Heading"].iloc[0]
    assert heading["heading"].startswith("What about")
    assert "first sentence" in heading["where_to_use_it"]


def test_unknown_sections_become_new(ctx):
    table = run(ctx).table
    assert set(table["where_on_site"]) >= {"/cost/inground-pool-cost/"}
    assert any(url.startswith("/") and "/nowhere/" not in url for url in table["where_on_site"])


def test_plan_reads_like_instructions(ctx):
    report = run(ctx).report
    assert report is not None
    assert report.startswith("# Content plan for www.example.com")
    assert "Write first" in report
    assert "### Main keyword: “inground pool cost”" in report
    assert "- [ ] Page title (the blue link in Google)" in report
    assert rules.HEADING_RULES[0] in report
    assert rules.INTENTS["compare"].layout[0] in report  # comparison page gets its checklist
    assert "Link to this page from" in report
    assert "**Same search:**" in report  # identical rewordings are called out


def test_lone_small_topics_are_added_as_sections(ctx):
    result = run(ctx)
    assert result.metrics["Added as sections"] >= 1
    assert "Added as sections" in result.report


def displayed_form_text() -> list[str]:
    """Labels, help text and choices the form shows (not internal ids like tool names)."""
    shown = []
    for field in KeywordPlannerInputs.model_json_schema()["properties"].values():
        shown += [field.get("title", ""), field.get("description", "")]
        shown += list(field.get("x-labels", {}).values())
    return shown


def test_nothing_the_user_sees_contains_jargon(ctx):
    result = run(ctx)
    shown = [
        result.report or "",
        *result.notes,
        *map(str, result.metrics),
        KeywordPlanner.title,
        KeywordPlanner.summary,
        KeywordPlanner.description(),
        *displayed_form_text(),
        result.table.drop(columns=["keyword", "heading"]).to_csv(),
        *(guide.label + " ".join(guide.layout) for guide in rules.INTENTS.values()),
    ]
    text = "\n".join(shown).lower()
    found = [word for word in rules.JARGON if re.search(rf"\b{re.escape(word)}\b", text)]
    assert found == []


def test_uses_keywords_and_evidence_from_a_previous_run(ctx):
    previous = pd.DataFrame(
        {
            "query": [*COST, "pool lights"],
            "evidence": ["observed", "model only", "partial", "observed"],
        }
    )
    ctx.connectors["run_table"] = lambda run_id: previous
    result = KeywordPlanner().run(
        KeywordPlannerInputs(keywords=["pool fence rules"], from_run="20261117-100000-abcdef"), ctx
    )
    table = result.table.set_index("keyword")
    assert set(table.index) == {*COST, "pool lights", "pool fence rules"}
    assert table.loc["inground pool cost", "evidence"] == "confirmed"  # older label, read as new
    assert table.loc["pool lights", "use_as"] == "Main keyword"  # really searched: its own page


def test_site_without_a_description_gets_a_tip(settings, gemini):
    create_site(settings, SiteConfig(name="bare", domain="https://bare.com/"))
    ctx = RunContext(settings, load_site("bare", settings), connectors={"gemini": gemini})
    result = run(ctx)
    assert any("Sites page" in note for note in result.notes)
    assert "(not described yet)" in gemini.prompts[0]


def test_pages_answering_the_same_question_are_merged(ctx, gemini):
    calls = []

    def plans(prompt):
        answer = plans_from_prompt(prompt)
        calls.append(len(answer["pages"]))
        if len(calls) == 1:  # first pass: say the permits page duplicates the cost page
            ids = {p["url_slug"]: p["page"] for p in answer["pages"]}
            cost = next(i for slug, i in ids.items() if "cost" in slug)
            permit = next(i for slug, i in ids.items() if "permit" in slug)
            answer["pages"][permit]["same_as"] = cost
        return answer

    gemini.answers["PagePlans"] = plans
    table = run(ctx).table
    cost_page = table.loc[table["keyword"] == "inground pool cost", "page"].item()
    assert set(PERMITS) <= set(table.loc[table["page"] == cost_page, "keyword"])
    assert calls[1] == 1  # only the merged page was planned again


def test_identical_main_headings_are_merged(ctx, gemini):
    def same_h1(prompt):
        answer = plans_from_prompt(prompt)
        for page in answer["pages"]:
            page["h1"] = "Everything about pools"
        return answer

    gemini.answers["PagePlans"] = same_h1
    pages = run(ctx).table["page"]
    assert (pages == pages.iloc[0]).all()


def test_gemini_chooses_the_broadest_main_keyword(ctx, gemini):
    def broadest(prompt):
        answer = plans_from_prompt(prompt)
        for page in answer["pages"]:
            if "cost" in page["url_slug"]:
                page["main_keyword"] = "inground pool price"
        return answer

    gemini.answers["PagePlans"] = broadest
    table = run(ctx).table
    main = table[(table["use_as"] == "Main keyword") & table["keyword"].isin(COST)]
    assert main["keyword"].tolist() == ["inground pool price"]
