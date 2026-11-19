"""The content editor: what a page should include (the brief), and how a draft measures up.

    brief = Brief.model_validate(run_data)          # made by tools/content/content_editor.py
    score = score_draft(brief, title, meta, slug, html, verdicts)
    score.score, score.label                        # 0-100 and "Good"
    score.terms                                     # each word to use: used 2 of 3-6 times
    score.checks                                    # the checklist, with what to fix and where

Scoring is plain counting, fast enough to run on every pause in typing. Whether each
question is really *answered* takes Gemini (see check_answers in the tool); its verdicts
are passed in and shown alongside.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.content import STOP_WORDS, Document, PhraseCounter, key_of, stem, words

Importance = Literal["must", "should", "nice"]
IMPORTANCE_LABELS: dict[str, str] = {
    "must": "Must use",
    "should": "Should use",
    "nice": "Nice to have",
}
IMPORTANCE_WEIGHT: dict[str, float] = {"must": 3.0, "should": 2.0, "nice": 1.0}
TermStatus = Literal["missing", "low", "good", "over"]
AnswerStatus = Literal["answered", "partly", "missing"]
QuestionStatus = Literal["missing", "heading", "partly", "answered"]
CheckGroup = Literal["Main keyword", "Answers", "Easy to read"]
QUESTION_WORDS = {
    "what", "how", "why", "when", "where", "which", "who", "can", "do", "does", "is", "are",
    "should", "will",
}  # fmt: skip
# Out of 100
WEIGHTS = {"Words to use": 45, "Questions answered": 25, "Checklist": 20, "Length": 10}
SHORT_DRAFT = 50  # words: below this, "no problems found" means nothing yet


# --- The brief -------------------------------------------------------------------------


class BriefTerm(BaseModel):
    term: str
    importance: Importance
    min: int
    max: int
    pages: int = 0  # how many of the top pages use it; 0 = suggested by Gemini
    main: bool = False  # the page's main keyword


class BriefQuestion(BaseModel):
    heading: str
    searches: list[str] = []  # the searches this section answers
    what_to_say: str = ""


class TopPage(BaseModel):
    url: str
    domain: str
    title: str
    word_count: int
    headings: list[str]


class Brief(BaseModel):
    keyword: str
    country: str
    language: str
    reader_wants: str  # e.g. "Compare options"
    page_type: str
    layout: list[str]  # checklist for this kind of page
    title: str
    h1: str
    meta_description: str
    url_slug: str
    words_min: int
    words_max: int
    headings_min: int
    headings_max: int
    terms: list[BriefTerm]
    questions: list[BriefQuestion]
    pages: list[TopPage]


class AnswerVerdict(BaseModel):
    """Gemini's view of whether the draft answers one of the brief's questions."""

    question: str
    status: AnswerStatus
    section: str = ""  # the draft's heading where it's answered
    fix: str = ""  # what to write, in a sentence or two
    place_after: str = ""  # for a missing answer: the heading to put it after


# --- The score -------------------------------------------------------------------------


class Meter(BaseModel):
    count: int
    min: int
    max: int


class TermScore(BaseModel):
    term: str
    importance: Importance
    main: bool
    pages: int
    count: int
    min: int
    max: int
    status: TermStatus


class QuestionScore(BaseModel):
    heading: str
    searches: list[str]
    what_to_say: str
    status: QuestionStatus
    section: str = ""  # the draft's heading that covers it
    fix: str = ""
    place_after: str = ""
    checked: bool = False  # True once Gemini has looked at it


class Fix(BaseModel):
    text: str
    section: str = ""  # heading to jump to in the draft, if it's about one section


class CheckScore(BaseModel):
    id: str
    group: CheckGroup
    label: str
    done: bool
    fixes: list[Fix] = []


class Score(BaseModel):
    score: int
    label: str
    words: Meter
    headings: Meter
    terms: list[TermScore]
    questions: list[QuestionScore]
    checks: list[CheckScore]
    parts: dict[str, int]  # points out of WEIGHTS for each part


# --- Scoring ---------------------------------------------------------------------------


def _content_stems(text: str) -> set[str]:
    return {stem(w) for w in words(text) if w not in STOP_WORDS}


def contains_keyword(text: str, keyword: str) -> bool:
    """The exact phrase (plurals allowed), or every meaningful word of it in any order."""
    if PhraseCounter([text]).count(keyword):
        return True
    needed = _content_stems(keyword)
    return bool(needed) and needed <= _content_stems(text)


def _slug_has_keyword(slug: str, keyword: str) -> bool:
    parts = {stem(p) for p in re.split(r"[^a-z0-9]+", slug.lower()) if p}
    needed = _content_stems(keyword)
    return bool(needed) and needed <= parts


def term_status(count: int, low: int, high: int) -> TermStatus:
    if count == 0:
        return "missing"
    if count < low:
        return "low"
    return "over" if count > high else "good"


def _is_question(heading: str) -> bool:
    first = words(heading)[:1]
    return heading.rstrip().endswith("?") or (bool(first) and first[0] in QUESTION_WORDS)


def matching_heading(question: str, doc: Document) -> str:
    """The draft's subheading that asks the same question, or ""."""
    wanted = _content_stems(question)
    best, best_overlap = "", 0.0
    for section in doc.subheadings:
        if not wanted:
            break
        overlap = len(wanted & _content_stems(section.heading)) / len(wanted)
        if overlap > best_overlap:
            best, best_overlap = section.heading, overlap
    return best if best_overlap >= 0.6 else ""


def _score_questions(
    brief: Brief, doc: Document, verdicts: list[AnswerVerdict]
) -> list[QuestionScore]:
    by_question = {v.question.strip().lower(): v for v in verdicts}
    result = []
    for question in brief.questions:
        heading = matching_heading(question.heading, doc)
        item = QuestionScore(
            heading=question.heading,
            searches=question.searches,
            what_to_say=question.what_to_say,
            status="heading" if heading else "missing",
            section=heading,
        )
        verdict = by_question.get(question.heading.strip().lower())
        if verdict is not None:
            item.checked = True
            item.status = verdict.status
            item.section = verdict.section or heading
            item.fix = verdict.fix
            item.place_after = verdict.place_after
            if verdict.status == "missing" and heading and not verdict.section:
                item.status, item.checked = "heading", False  # added since the check
        result.append(item)
    return result


def _checks(brief: Brief, doc: Document, title: str, meta: str, slug: str) -> list[CheckScore]:
    keyword = brief.keyword
    tips = rules.TIPS
    intro = doc.intro
    checks: list[CheckScore] = []

    def add(id_: str, group: CheckGroup, fixes: list[Fix]) -> None:
        checks.append(
            CheckScore(id=id_, group=group, label=rules.CHECKS[id_], done=not fixes, fixes=fixes)
        )

    def tip(id_: str, **values: object) -> list[Fix]:
        return [Fix(text=tips[id_].format(keyword=keyword, **values))]

    # Main keyword: where it goes
    add(
        "keyword_title",
        "Main keyword",
        [] if contains_keyword(title, keyword) else tip("keyword_title"),
    )
    h1 = doc.h1s[0] if doc.h1s else ""
    add("keyword_h1", "Main keyword", [] if contains_keyword(h1, keyword) else tip("keyword_h1"))
    add(
        "keyword_url",
        "Main keyword",
        [] if _slug_has_keyword(slug, keyword) else tip("keyword_url", slug=brief.url_slug),
    )
    first = intro.first_sentence if intro else ""
    add(
        "keyword_intro",
        "Main keyword",
        [] if contains_keyword(first, keyword) else tip("keyword_intro"),
    )
    add(
        "keyword_meta",
        "Main keyword",
        [] if contains_keyword(meta, keyword) else tip("keyword_meta"),
    )

    low, high = rules.TITLE_LENGTH
    n = len(title.strip())
    add(
        "title_length",
        "Main keyword",
        tip("title_short", n=n) if n < low else tip("title_long", n=n) if n > high else [],
    )
    low, high = rules.META_LENGTH
    n = len(meta.strip())
    add(
        "meta_length",
        "Main keyword",
        tip("meta_missing")
        if n == 0
        else tip("meta_short", n=n)
        if n < low
        else tip("meta_long", n=n)
        if n > high
        else [],
    )
    h1_count = len(doc.h1s)
    add(
        "one_h1",
        "Main keyword",
        tip("no_h1") if h1_count == 0 else tip("many_h1", n=h1_count) if h1_count > 1 else [],
    )

    # Answers: question headings answered straight away, in words that stand alone
    short = doc.word_count < SHORT_DRAFT
    first_fixes: list[Fix] = []
    alone_fixes: list[Fix] = []
    for section in doc.subheadings:
        if not _is_question(section.heading):
            continue
        sentence = section.first_sentence
        if not section.paragraphs or len(words(sentence)) > rules.ANSWER_WORDS:
            first_fixes.append(
                Fix(
                    text=tips["answer_first"].format(heading=section.heading),
                    section=section.heading,
                )
            )
        opening = words(sentence)[:1]
        if opening and opening[0] in rules.LEANING_WORDS:
            word = sentence.split()[0].strip(",.;:")
            alone_fixes.append(
                Fix(
                    text=tips["stand_alone"].format(heading=section.heading, word=word),
                    section=section.heading,
                )
            )
    add("answers_first", "Answers", first_fixes)
    add("answers_stand_alone", "Answers", alone_fixes)

    # Easy to read
    long_fixes: list[Fix] = []
    vague_fixes: list[Fix] = []
    empty_fixes: list[Fix] = []
    for i, section in enumerate(doc.sections):
        name = section.heading or "the introduction"
        for paragraph in section.paragraphs:
            n = len(words(paragraph))
            if n > rules.LONG_PARAGRAPH:
                long_fixes.append(
                    Fix(
                        text=tips["long_paragraph"].format(heading=name, n=n),
                        section=section.heading,
                    )
                )
                break
        text = " " + " ".join(words(section.text)) + " "
        vague = next((w for w in rules.VAGUE_WORDS if f" {w} " in text), None)
        if vague:
            vague_fixes.append(
                Fix(text=tips["vague"].format(heading=name, word=vague), section=section.heading)
            )
        following = doc.sections[i + 1] if i + 1 < len(doc.sections) else None
        if (
            section.level >= 2
            and not section.paragraphs
            and not _is_question(section.heading)  # those are under "Answers"
            and (following is None or following.level <= section.level)
        ):
            empty_fixes.append(
                Fix(
                    text=tips["empty_section"].format(heading=section.heading),
                    section=section.heading,
                )
            )
    add("short_paragraphs", "Easy to read", long_fixes)
    add("exact_numbers", "Easy to read", vague_fixes)
    add("no_empty_sections", "Easy to read", empty_fixes)

    if short:  # an empty draft has no problems, but nothing done either
        for check in checks:
            if check.group != "Main keyword" and check.done:
                check.done = False
    return checks


_TERM_CREDIT: dict[str, float] = {"good": 1.0, "over": 0.7, "low": 0.5, "missing": 0.0}
_QUESTION_CREDIT: dict[str, float] = {
    "answered": 1.0,
    "heading": 0.6,
    "partly": 0.5,
    "missing": 0.0,
}


def score_draft(
    brief: Brief,
    title: str,
    meta_description: str,
    url_slug: str,
    html: str,
    verdicts: list[AnswerVerdict] | None = None,
) -> Score:
    doc = Document.from_html(html)
    counter = doc.counter()
    terms = []
    for term in brief.terms:
        count = counter.count(key_of(term.term))
        terms.append(
            TermScore(
                **term.model_dump(),
                count=count,
                status=term_status(count, term.min, term.max),
            )
        )
    questions = _score_questions(brief, doc, verdicts or [])
    checks = _checks(brief, doc, title, meta_description, url_slug)
    word_count = doc.word_count

    weight = sum(IMPORTANCE_WEIGHT[t.importance] for t in terms) or 1.0
    term_share = (
        sum(IMPORTANCE_WEIGHT[t.importance] * _TERM_CREDIT[t.status] for t in terms) / weight
    )
    question_share = (
        sum(_QUESTION_CREDIT[q.status] for q in questions) / len(questions) if questions else 1.0
    )
    check_share = sum(c.done for c in checks) / len(checks) if checks else 1.0
    length_share = min(1.0, word_count / brief.words_min) if brief.words_min else 1.0
    shares = {
        "Words to use": term_share,
        "Questions answered": question_share,
        "Checklist": check_share,
        "Length": length_share if word_count else 0.0,
    }
    parts = {name: round(WEIGHTS[name] * share) for name, share in shares.items()}
    total = round(sum(WEIGHTS[name] * share for name, share in shares.items()))
    label = next(text for floor, text in rules.SCORE_LABELS if total >= floor)
    return Score(
        score=total,
        label=label,
        words=Meter(count=word_count, min=brief.words_min, max=brief.words_max),
        headings=Meter(count=len(doc.subheadings), min=brief.headings_min, max=brief.headings_max),
        terms=terms,
        questions=questions,
        checks=checks,
        parts=parts,
    )
