"""Scoring a draft against its brief: counting only, no Gemini."""

import re

import pytest

from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.editor import (
    AnswerVerdict,
    Brief,
    BriefQuestion,
    BriefTerm,
    contains_keyword,
    score_draft,
    term_status,
)


@pytest.fixture
def brief() -> Brief:
    return Brief(
        keyword="inground pool cost",
        country="us",
        language="en",
        reader_wants="Compare options",
        page_type="pricing page",
        layout=list(rules.INTENTS["compare"].layout),
        title="Inground pool cost in 2026",
        h1="How much does an inground pool cost?",
        meta_description="",
        url_slug="inground-pool-cost",
        words_min=150,
        words_max=300,
        headings_min=2,
        headings_max=4,
        terms=[
            BriefTerm(
                term="inground pool cost", importance="must", min=2, max=3, pages=5, main=True
            ),
            BriefTerm(term="fiberglass pool", importance="must", min=1, max=2, pages=4),
            BriefTerm(term="maintenance", importance="should", min=1, max=3, pages=3),
            BriefTerm(term="pool permit", importance="nice", min=1, max=1, pages=0),
        ],
        questions=[
            BriefQuestion(
                heading="How much does a fiberglass pool cost?",
                searches=["fiberglass pool cost"],
                what_to_say="Give the installed price range.",
            ),
            BriefQuestion(heading="Do I need a pool permit?", searches=["pool permit texas"]),
        ],
        pages=[],
    )


GOOD = """
<h1>Inground pool cost: what to budget in 2026</h1>
<p>The average inground pool cost is $65,000 in 2026, and most homes pay between $45,000
and $85,000 depending on size and material. That price includes the dig, the shell and the
patio around it, which is what most families need for a backyard they will use for years.</p>
<h2>How much does a fiberglass pool cost?</h2>
<p>A fiberglass pool costs $45,000 to $85,000 installed, about the same inground pool cost as
vinyl over ten years once you count upkeep. The shell arrives in one piece, so the work takes
two to three weeks instead of two months.</p>
<h2>What does maintenance cost?</h2>
<p>Maintenance runs about $1,200 a year for chemicals, power and small repairs on a family
pool, and less if you add a cover that keeps out leaves and slows evaporation in summer.</p>
"""

WEAK = """
<h1>Our pools</h1>
<p>We build many pools.</p>
<h2>What does upkeep cost?</h2>
<p>It depends.</p>
<h2>Gallery</h2>
"""


def score(brief, html, title="Inground pool cost in 2026: a full price guide", **fields):
    defaults = {
        "meta_description": "What an inground pool costs in 2026: prices for fiberglass, vinyl "
        "and concrete pools, the extras to budget for, and the yearly upkeep.",
        "url_slug": "inground-pool-cost",
    }
    defaults.update(fields)
    return score_draft(brief, title, defaults["meta_description"], defaults["url_slug"], html)


def checks(result):
    return {c.id: c for c in result.checks}


def test_term_status():
    assert [term_status(n, 2, 4) for n in (0, 1, 3, 5)] == ["missing", "low", "good", "over"]


def test_keyword_found_as_a_phrase_or_its_words():
    assert contains_keyword("Inground Pools Cost guide", "inground pool cost")
    assert contains_keyword("The cost of an inground pool", "inground pool cost")
    assert not contains_keyword("Pool cost guide", "inground pool cost")


def test_a_good_draft_scores_well_and_a_weak_one_badly(brief):
    good, weak = score(brief, GOOD), score(brief, WEAK, title="Pools")
    assert good.score >= 75 and good.label in ("Good", "Great")
    assert weak.score < 40 and weak.label == "Needs work"
    assert set(good.parts) == {"Words to use", "Questions answered", "Checklist", "Length"}
    assert sum(good.parts.values()) == pytest.approx(good.score, abs=2)


def test_words_to_use_are_counted(brief):
    terms = {t.term: t for t in score(brief, GOOD).terms}
    # Once in the H1 and twice in the text
    assert terms["inground pool cost"].count == 3 and terms["inground pool cost"].status == "good"
    assert terms["fiberglass pool"].status == "good"
    assert terms["maintenance"].count == 2  # heading and paragraph
    assert terms["pool permit"].status == "missing"
    assert terms["inground pool cost"].main


def test_length_and_headings_are_measured(brief):
    result = score(brief, GOOD)
    assert result.words.min == 150 and 100 < result.words.count < 200
    assert result.headings.count == 2


def test_questions_with_a_matching_heading(brief):
    questions = {q.heading: q for q in score(brief, GOOD).questions}
    fiberglass = questions["How much does a fiberglass pool cost?"]
    assert fiberglass.status == "heading" and fiberglass.section == fiberglass.heading
    assert questions["Do I need a pool permit?"].status == "missing"


def test_gemini_verdicts_are_shown(brief):
    verdicts = [
        AnswerVerdict(
            question="How much does a fiberglass pool cost?",
            status="partly",
            section="How much does a fiberglass pool cost?",
            fix="Add what's included in the price.",
        ),
        AnswerVerdict(
            question="Do I need a pool permit?",
            status="missing",
            fix="Say which permits Texas cities ask for.",
            place_after="What does maintenance cost?",
        ),
    ]
    result = score_draft(brief, "t", "m", "s", GOOD, verdicts)
    questions = {q.heading: q for q in result.questions}
    partly = questions["How much does a fiberglass pool cost?"]
    assert (partly.status, partly.checked, partly.fix) == (
        "partly",
        True,
        "Add what's included in the price.",
    )
    permit = questions["Do I need a pool permit?"]
    assert permit.place_after == "What does maintenance cost?"
    # A heading added since the check counts, and needs checking again
    added = GOOD + "<h2>Do I need a pool permit?</h2><p>Yes, most cities ask for one.</p>"
    permit = {q.heading: q for q in score_draft(brief, "t", "m", "s", added, verdicts).questions}[
        "Do I need a pool permit?"
    ]
    assert (permit.status, permit.checked) == ("heading", False)


def test_main_keyword_places(brief):
    good = checks(score(brief, GOOD))
    assert all(
        good[i].done
        for i in ("keyword_title", "keyword_h1", "keyword_url", "keyword_intro", "keyword_meta")
    )
    weak = checks(score(brief, WEAK, title="Pools", meta_description="", url_slug="pools"))
    assert not weak["keyword_h1"].done
    assert (
        weak["keyword_title"].fixes[0].text
        == "Put “inground pool cost” near the start of the page title."
    )
    assert "/inground-pool-cost/" in weak["keyword_url"].fixes[0].text
    assert weak["meta_length"].fixes[0].text.startswith("Write a meta description")


def test_lengths_and_main_headings(brief):
    result = checks(
        score(
            brief,
            GOOD.replace("<h2>What", "<h1>What").replace("cost?</h2>", "cost?</h1>"),
            title="Pool cost",
        )
    )
    assert "9 characters" in result["title_length"].fixes[0].text
    assert "main headings (H1)" in result["one_h1"].fixes[0].text
    long_title = checks(score(brief, GOOD, title="x" * 70))["title_length"]
    assert "Google will cut it off" in long_title.fixes[0].text


def test_answers_must_come_first_and_stand_alone(brief):
    rambling = " ".join(["word"] * 60)
    html = (
        GOOD
        + f"<h2>Why is concrete slower?</h2><p>{rambling}.</p>"
        + "<h2>Is vinyl cheaper?</h2><p>It is, by about $10,000.</p>"
    )
    result = checks(score(brief, html))
    first = result["answers_first"]
    assert not first.done and first.fixes[0].section == "Why is concrete slower?"
    alone = result["answers_stand_alone"].fixes
    assert alone[0].text == (
        "Under “Is vinyl cheaper?”, start with the subject instead of “It”, so the answer "
        "makes sense on its own."
    )


def test_readability_checks_point_at_the_section(brief):
    result = checks(score(brief, WEAK + "<h2>Sizes</h2><p>" + "pool " * 130 + "</p>"))
    assert (
        result["exact_numbers"].fixes[0].text
        == "Under “Our pools”, replace “many” with an exact number."
    )
    assert result["no_empty_sections"].fixes[0].section == "Gallery"
    assert result["short_paragraphs"].fixes[0].section == "Sizes"


def test_an_empty_draft_gets_no_free_points(brief):
    result = score_draft(brief, "", "", "", "")
    assert result.score == 0
    assert not any(c.done for c in result.checks if c.group != "Main keyword")


def test_checklist_wording_has_no_jargon():
    text = " ".join(
        [*rules.CHECKS.values(), *rules.TIPS.values(), *(label for _, label in rules.SCORE_LABELS)]
    )
    assert [w for w in rules.JARGON if re.search(rf"\b{re.escape(w)}\b", text.lower())] == []


def test_empty_question_sections_count_as_unanswered(brief):
    result = checks(score(brief, GOOD + "<h2>Do I need a pool permit?</h2><h2>Gallery</h2>"))
    assert [f.section for f in result["answers_first"].fixes] == ["Do I need a pool permit?"]
    assert [f.section for f in result["no_empty_sections"].fixes] == ["Gallery"]


def test_a_question_left_empty_stays_unanswered_after_a_check(brief):
    html = GOOD + "<h2>Do I need a pool permit?</h2>"
    verdict = AnswerVerdict(
        question="Do I need a pool permit?",
        status="missing",
        section="Do I need a pool permit?",  # the heading was there, with nothing under it
        fix="Say which permits cities ask for.",
    )
    permit = score_draft(brief, "t", "m", "s", html, [verdict]).questions[1]
    assert (permit.status, permit.checked, permit.section) == (
        "missing",
        True,
        "Do I need a pool permit?",
    )
