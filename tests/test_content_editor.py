"""The content editor's brief: top pages read, words chosen, questions planned."""

import re

import pytest

from fakes import DictAutocomplete, FakeGemini, FakePages
from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.config import SiteConfig
from seo_toolkit.core.editor import Brief
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.sites import create_site, load_site
from seo_toolkit.tools.base import RunContext, discover
from seo_toolkit.tools.content.content_editor import (
    MAX_MUST,
    ContentEditor,
    ContentEditorInputs,
    check_answers,
)

FILLER = (
    "Homeowners often ask us about this when they plan a backyard project, so we keep the "
    "advice simple and practical, with real numbers from recent jobs across the state. "
)


def article(title: str, *paragraphs: str) -> str:
    body = "".join(
        f"<h2>{p.split('|')[0]}</h2><p>{p.split('|')[1]} {FILLER}{FILLER}</p>" for p in paragraphs
    )
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1>{body}</article></body></html>"
    )


TOP_PAGES = {
    "https://r/1": (
        "https://www.a.com/pool-cost/",
        article(
            "Inground pool cost guide",
            "Fiberglass pool cost|A fiberglass pool costs $45,000 to $85,000, a vinyl liner less.",
            "Maintenance cost|Yearly maintenance cost is about $1,200 for chemicals and power.",
            "Pool permit|A pool permit is needed in most Texas cities before digging.",
        ),
    ),
    "https://r/2": (
        "https://b.org/inground-pools/",
        article(
            "What an inground pool costs",
            "Fiberglass or vinyl liner|A fiberglass pool lasts longer than a vinyl liner pool.",
            "Maintenance cost|Budget a maintenance cost of $1,000 to $1,500 a year.",
            "Pool permit fees|Pool permit fees run $300 to $1,000 depending on the city.",
        ),
    ),
    "https://pasted.com/costs/": article(
        "Pool prices",
        "Fiberglass pool prices|Most fiberglass pool installs cost $60,000 with a vinyl liner.",
        "Maintenance cost|The maintenance cost of a pool depends on the pump and heater.",
        "Excavation|Excavation adds $5,000 when the soil is rocky.",
    ),
}


def plan_from_prompt(prompt: str) -> dict:
    """Answer like Gemini: every listed word as a must, plus one extra term and two questions."""
    listed = prompt.split("## Words and phrases the top-ranking pages share")[1].split("##")[0]
    terms = [{"term": t, "importance": "must"} for t in re.findall(r"^- (.+): \d+$", listed, re.M)]
    return {
        "terms": terms,
        "extra_terms": ["pool fence", "Maintenance Cost"],  # the second is already listed
        "intent": "compare",
        "page_type": "pricing page",
        "title": "Inground pool cost in 2026",
        "h1": "How much does an inground pool cost?",
        "meta_description": "Prices for every kind of inground pool.",
        "url_slug": "Inground Pool Cost!",
        "questions": [
            {
                "heading": "How much does a fiberglass pool cost?",
                "searches": ["Fiberglass vs concrete pool", "not one of the searches"],
                "what_to_say": "Give the installed price range.",
            },
            {"heading": "Do I need a pool permit?", "searches": [], "what_to_say": ""},
        ],
    }


@pytest.fixture
def gemini():
    fake = FakeGemini(
        generated=[
            {
                "query": "fiberglass vs concrete pool",
                "fanout_type": "comparative",
                "intent": "commercial",
                "entity": "pool",
                "attribute": "material",
                "lexical_relation": "none",
                "rationale": "choosing",
            }
        ],
        searches=("inground pool cost texas",),
    )
    fake.answers["BriefPlan"] = plan_from_prompt
    return fake


@pytest.fixture
def pages():
    return FakePages(TOP_PAGES)


@pytest.fixture
def ctx(settings, gemini, pages):
    return RunContext(
        settings,
        load_site("example", settings),
        connectors={"gemini": gemini, "pages": pages, "autocomplete": DictAutocomplete()},
    )


def run(ctx, **inputs):
    return ContentEditor().run(
        ContentEditorInputs.model_validate({"keyword": "Inground Pool Cost", **inputs}), ctx
    )


def test_registered_with_its_own_screen(settings):
    tool = discover()["content/content-editor"]
    assert tool.page == "/editor"
    assert tool.missing(settings) == ["GEMINI_API_KEY"]


def test_inputs_are_cleaned():
    inputs = ContentEditorInputs.model_validate(
        {"keyword": " Pool Cost? ", "pages": ["", "www.a.com/x", "https://www.a.com/x"]}
    )
    assert inputs.keyword == "pool cost"
    assert inputs.pages == ["https://www.a.com/x"]
    with pytest.raises(ValueError, match="isn't a web address"):
        ContentEditorInputs.model_validate({"keyword": "pool", "pages": ["not a page"]})


def test_pasted_pages_come_first_then_the_ones_google_cites(ctx, pages):
    result = run(ctx, pages=["https://pasted.com/costs/"])
    assert pages.calls == ["https://pasted.com/costs/", "https://r/1", "https://r/2"]
    brief = Brief.model_validate(result.data)
    assert [p.domain for p in brief.pages] == ["pasted.com", "a.com", "b.org"]
    assert result.metrics["Top pages read"] == 3


def test_words_the_top_pages_share_with_targets(ctx):
    brief = Brief.model_validate(run(ctx, pages=["https://pasted.com/costs/"]).data)
    terms = {t.term: t for t in brief.terms}
    main = brief.terms[0]
    assert (main.term, main.main, main.importance) == ("inground pool cost", True, "must")
    assert main.min >= 2
    assert terms["maintenance cost"].pages == 3
    assert terms["fiberglass pool"].pages == 3 and terms["fiberglass pool"].min >= 1
    assert terms["pool fence"].pages == 0  # suggested by Gemini
    assert sum(t.term == "maintenance cost" for t in brief.terms) == 1
    # Words of the keyword on their own aren't targets: they come with the keyword
    assert not {"pool", "cost", "inground"} & set(terms)
    assert sum(t.importance == "must" for t in brief.terms) <= MAX_MUST


def test_questions_keep_only_real_searches(ctx):
    brief = Brief.model_validate(run(ctx).data)
    first = brief.questions[0]
    assert first.heading == "How much does a fiberglass pool cost?"
    assert first.searches == ["fiberglass vs concrete pool"]
    assert brief.url_slug == "inground-pool-cost"
    assert brief.reader_wants == "Compare options"
    assert brief.layout == list(rules.INTENTS["compare"].layout)


def test_the_site_itself_and_video_sites_are_not_learned_from(settings, gemini, pages):
    site = load_site("example", settings)
    ctx = RunContext(
        settings,
        site,
        connectors={"gemini": gemini, "pages": pages, "autocomplete": DictAutocomplete()},
    )
    own = site.domain.split("//")[1].strip("/")
    run(ctx, pages=[f"https://{own}/our-prices/", "https://www.youtube.com/watch?v=1"])
    assert pages.calls == ["https://r/1", "https://r/2"]


def test_blocked_pages_are_named_and_none_read_falls_back_to_suggestions(ctx, pages):
    pages.pages = {}
    result = run(ctx)
    assert any("Couldn't read 2 of the top pages (a.com, b.org)" in n for n in result.notes)
    assert any("Gemini's suggestions" in n for n in result.notes)
    brief = Brief.model_validate(result.data)
    assert (brief.words_min, brief.words_max) == (1200, 2000)  # a comparison page's default
    assert {t.term for t in brief.terms} == {"inground pool cost", "pool fence", "maintenance cost"}


def test_writers_brief_and_table(ctx):
    result = run(ctx)
    report = result.report
    assert report.startswith("# Writer's brief: “inground pool cost”")
    assert "**Kind of page:** pricing page" in report
    assert (
        "1. **How much does a fiberglass pool cost?** — Give the installed price range." in report
    )
    assert "| **inground pool cost** (main keyword) |" in report
    assert rules.INTENTS["compare"].layout[0] in report
    table = result.table.set_index("term")
    assert table.loc["inground pool cost", "importance"] == "Main keyword"
    assert table.loc["pool fence", "used_by"] == "Suggested by Gemini"
    assert table.loc["maintenance cost", "used_by"] == "2 of 2 top pages"


def test_nothing_the_user_sees_contains_jargon(ctx):
    result = run(ctx)
    schema = ContentEditorInputs.model_json_schema()["properties"].values()
    shown = [
        result.report or "",
        *result.notes,
        *map(str, result.metrics),
        ContentEditor.title,
        ContentEditor.summary,
        ContentEditor.description(),
        *(f.get("title", "") + " " + f.get("description", "") for f in schema),
        result.table.drop(columns=["term"]).to_csv(),
    ]
    text = "\n".join(shown).lower()
    assert [w for w in rules.JARGON if re.search(rf"\b{re.escape(w)}\b", text)] == []


def test_site_without_a_description_gets_a_tip(settings, gemini, pages):
    create_site(settings, SiteConfig(name="bare", domain="https://bare.com/"))
    ctx = RunContext(
        settings,
        load_site("bare", settings),
        connectors={"gemini": gemini, "pages": pages, "autocomplete": DictAutocomplete()},
    )
    assert any("Sites page" in n for n in run(ctx).notes)


# --- Checking answers ------------------------------------------------------------------

DRAFT = (
    "<h1>Inground pool cost</h1><p>An inground pool costs $65,000 on average in 2026. "
    + FILLER
    + "</p><h2>How much does a fiberglass pool cost?</h2><p>About $45,000 to $85,000. "
    + FILLER
    + "</p>"
)


def test_answer_check_names_sections_and_where_to_add(ctx, gemini):
    brief = Brief.model_validate(run(ctx).data)
    gemini.answers["Verdicts"] = {
        "verdicts": [
            {"question": 1, "status": "partly", "section": 2, "fix": "Say what's included."},
            {"question": 2, "status": "missing", "place_after": 2},
        ]
    }
    verdicts = check_answers(gemini, brief, DRAFT)
    assert verdicts[0].section == "How much does a fiberglass pool cost?"
    assert verdicts[0].fix == "Say what's included."
    assert verdicts[1].place_after == "How much does a fiberglass pool cost?"
    assert "[2] How much does a fiberglass pool cost?" in gemini.prompts[-1]
    assert (
        "[1] How much does a fiberglass pool cost? — Give the installed price range."
        in gemini.prompts[-1]
    )


def test_questions_gemini_skips_count_as_missing(ctx, gemini):
    brief = Brief.model_validate(run(ctx).data)
    gemini.answers["Verdicts"] = {"verdicts": [{"question": 1, "status": "answered", "section": 9}]}
    verdicts = check_answers(gemini, brief, DRAFT)
    assert (verdicts[0].status, verdicts[0].section, verdicts[0].fix) == ("answered", "", "")
    assert verdicts[1].status == "missing"


def test_answer_check_needs_some_text(ctx, gemini):
    brief = Brief.model_validate(run(ctx).data)
    with pytest.raises(ToolkitError, match="Write a little more first"):
        check_answers(gemini, brief, "<p>Hello</p>")


def test_answer_check_names_headings_instead_of_section_numbers(ctx, gemini):
    brief = Brief.model_validate(run(ctx).data)
    gemini.answers["Verdicts"] = {
        "verdicts": [
            {
                "question": 1,
                "status": "partly",
                "section": 2,
                "fix": "Move the price from Section 1 into Section 2.",
            },
            {"question": 2, "status": "missing", "fix": "Add it after section 9."},
        ]
    }
    verdicts = check_answers(gemini, brief, DRAFT)
    assert verdicts[0].fix == (
        "Move the price from the section “Inground pool cost” into the section "
        "“How much does a fiberglass pool cost?”."
    )
    assert verdicts[1].fix == "Add it after another section."  # there's no section 9


def test_a_missing_answer_points_at_its_empty_heading(ctx, gemini):
    brief = Brief.model_validate(run(ctx).data)
    gemini.answers["Verdicts"] = {"verdicts": [{"question": 2, "status": "missing"}]}
    draft = DRAFT + "<h2>Do I need a pool permit?</h2>"
    verdicts = check_answers(gemini, brief, draft)
    assert (verdicts[1].status, verdicts[1].section) == ("missing", "Do I need a pool permit?")
