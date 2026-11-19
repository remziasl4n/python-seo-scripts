"""Write a page that covers what the top-ranking pages cover, with a live score as you type.

**How it works**

1. **Read the top pages.** The pages Google's AI cites for your keyword, and any you paste
   in, are read. Only their main text counts: no menus, footers or ads.
2. **Find the words they share.** Words and phrases most of those pages use become your
   **words to use**, with how often to use each one in a page of your length.
3. **Find the questions.** The related searches people run (from Google autocomplete and
   the searches Google's AI makes) become **questions to answer**, as section headings in
   the order a reader needs them.
4. **Write.** The editor scores your draft as you type: words used, questions covered, a
   checklist for the title, headings and answers, and the length. **Check my answers**
   asks Gemini whether each question is really answered, and what to add where.

You can paste in an existing page to improve it, or start from the suggested outline.
"""

from __future__ import annotations

import dataclasses
import re
from statistics import median
from urllib.parse import urlsplit

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from seo_toolkit.connectors.gemini import Gemini
from seo_toolkit.connectors.pages import FetchedPage, PageError
from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.content import (
    Block,
    Candidate,
    Document,
    PhraseCounter,
    key_of,
    parse_html,
    shared_terms,
    typical_range,
    words,
)
from seo_toolkit.core.editor import (
    IMPORTANCE_LABELS,
    SHORT_DRAFT,
    AnswerStatus,
    AnswerVerdict,
    Brief,
    BriefQuestion,
    BriefTerm,
    Importance,
    TopPage,
    matching_heading,
)
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.output import slugify
from seo_toolkit.core.prompts import render
from seo_toolkit.tools.base import RunContext, Tool, ToolResult
from seo_toolkit.tools.research.query_fanout import (
    EVIDENCE_ORDER,
    QueryFanout,
    QueryFanoutInputs,
    grounding_system,
    normalize,
)

MAX_PAGES = 8  # top pages to learn from
MAX_ATTEMPTS = 12  # some pages block tools; stop trying after this many
PER_DOMAIN = 2
MIN_PAGE_WORDS = 150  # less than this is a page we couldn't really read
MAX_TERMS = 60
MAX_MUST = 12  # more "must use" words than this and none of them stands out
MAX_SEARCHES = 40
# Sites whose pages are videos, posts or pins rather than articles to learn from
SKIP_DOMAINS = (
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "pinterest.com",
    "linkedin.com",
)
# Length when no top page could be read, by what the reader wants
DEFAULT_LENGTH: dict[str, tuple[int, int]] = {
    "learn": (1200, 1800),
    "compare": (1200, 2000),
    "buy": (600, 1200),
    "find": (300, 600),
}
DEFAULT_HEADINGS = (6, 10)


class ContentEditorInputs(BaseModel):
    keyword: str = Field(
        min_length=2,
        title="Keyword",
        description="The search you want this page to rank for, e.g. 'inground pool cost'.",
    )
    pages: list[str] = Field(
        [],
        max_length=10,
        title="Top pages to learn from (optional)",
        description="Search Google for your keyword and paste the top results' addresses, "
        "one per line. Leave empty to use the pages Google's AI cites.",
    )
    country: str | None = Field(None, description="Two-letter code. Empty = the site's country.")
    language: str | None = Field(None, description="Two-letter code. Empty = the site's language.")

    @field_validator("keyword")
    @classmethod
    def _clean_keyword(cls, value: str) -> str:
        return normalize(value)

    @field_validator("pages")
    @classmethod
    def _clean_pages(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            value = value.strip()
            if not value:
                continue
            if "://" not in value:
                value = "https://" + value
            if not value.startswith(("http://", "https://")) or "." not in value:
                raise ValueError(f"{value} isn't a web address, e.g. https://www.example.com/page/")
            cleaned.append(value)
        return list(dict.fromkeys(cleaned))


# --- What Gemini returns -------------------------------------------------------------


class ChosenTerm(BaseModel):
    term: str
    importance: Importance


class PlannedQuestion(BaseModel):
    heading: str
    searches: list[str] = []
    what_to_say: str = ""


class BriefPlan(BaseModel):
    terms: list[ChosenTerm] = []
    extra_terms: list[str] = []
    intent: rules.Intent
    page_type: rules.PageType
    title: str
    h1: str
    meta_description: str
    url_slug: str
    questions: list[PlannedQuestion] = []


class Verdict(BaseModel):
    question: int
    status: AnswerStatus
    section: int | None = None
    fix: str = ""
    place_after: int | None = None


class Verdicts(BaseModel):
    verdicts: list[Verdict]


# --- The tool ------------------------------------------------------------------------


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _skipped(domain: str, own: str) -> bool:
    return domain == own or any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)


class ContentEditor(Tool):
    name = "content-editor"
    group = "content"
    title = "Content editor"
    summary = (
        "Write a page with a live score: the words to use, the questions to answer, and "
        "what to fix."
    )
    needs = ("gemini_api_key",)
    page = "/editor"
    Inputs = ContentEditorInputs

    def run(self, inputs: ContentEditorInputs, ctx: RunContext) -> ToolResult:
        site = ctx.site
        country = (inputs.country or site.country).lower()
        language = (inputs.language or site.language).lower()
        keyword = inputs.keyword
        notes: list[str] = []
        ctx.gemini.on_wait = lambda seconds: ctx.progress(
            0.8, f"Waiting {seconds:.0f}s for Gemini's free-plan limit…"
        )

        # 1. What people search for around the keyword
        searches = self._searches(keyword, country, language, ctx)

        # 2. The top pages, and what they have in common
        own = _domain(site.domain)
        sources = self._sources(keyword, inputs.pages, own, country, ctx, notes)
        pages, failed = self._read(sources, ctx)
        if failed:
            notes.append(
                f"Couldn't read {len(failed)} of the top pages ({', '.join(failed)}). Paste "
                "other addresses under “Top pages to learn from” to use different ones."
            )
        if not pages:
            notes.append(
                "No top pages could be read, so the words to use are Gemini's suggestions. "
                "For a better list, search Google for your keyword and paste the top results' "
                "addresses."
            )
        blocks = [parse_html(p.html) for p in pages]
        candidates = shared_terms(blocks)

        # 3. Gemini picks the terms that matter and plans the sections
        ctx.progress(0.8, "Choosing the words to use and planning the sections…")
        plan = ctx.gemini.generate_json(
            self._prompt(keyword, searches, candidates, pages, ctx, country, language), BriefPlan
        )
        brief = self._brief(keyword, plan, candidates, pages, blocks, searches, country, language)
        if not site.source_context.strip():
            notes.append(
                "Your site has no description yet, so the advice can't be matched to what you "
                "sell. Add one on the Sites page."
            )
        ctx.progress(1.0, "Done")
        metrics: dict[str, int | float | str] = {
            "Top pages read": len(pages),
            "Words to use": len(brief.terms),
            "Questions": len(brief.questions),
            "Target length": f"{brief.words_min:,}–{brief.words_max:,} words",
        }
        return ToolResult(
            self._table(brief), metrics, notes, self._report(brief), brief.model_dump(mode="json")
        )

    # --- Steps ---------------------------------------------------------------------------

    @staticmethod
    def _searches(
        keyword: str, country: str, language: str, ctx: RunContext
    ) -> list[tuple[str, str]]:
        """Related searches, best evidence first, without rewordings: (search, evidence)."""

        def progress(fraction: float, message: str) -> None:
            ctx.progress(0.02 + 0.33 * fraction, message)

        sub = dataclasses.replace(ctx, progress=progress)
        table = (
            QueryFanout()
            .run(
                QueryFanoutInputs.model_validate(
                    {"query": keyword, "per_type": 4, "country": country, "language": language}
                ),
                sub,
            )
            .table
        )
        if table.empty:
            return []
        table = table[table["same_as"] == ""].copy()
        table["_rank"] = table["evidence"].map(EVIDENCE_ORDER)
        table = table.sort_values("_rank", kind="stable").head(MAX_SEARCHES)
        return list(zip(table["query"], table["evidence"], strict=True))

    @staticmethod
    def _sources(
        keyword: str,
        pasted: list[str],
        own: str,
        country: str,
        ctx: RunContext,
        notes: list[str],
    ) -> list[tuple[str, str]]:
        """Pages to read, as (address, domain): the pasted ones, then those Google's AI cites."""
        found: list[tuple[str, str]] = [(url, _domain(url)) for url in pasted]
        gemini: Gemini = ctx.gemini
        if gemini.grounding:
            answer = gemini.ground(keyword, system=grounding_system(country))
            found += [(s.url, s.domain.removeprefix("www.")) for s in answer.sources]
        elif not pasted:
            notes.append(
                "Gemini's Google Search is turned off (GEMINI_GROUNDING=false), so no top pages "
                "were found. Paste their addresses under “Top pages to learn from”."
            )
        chosen: list[tuple[str, str]] = []
        per_domain: dict[str, int] = {}
        seen: set[str] = set()
        for url, domain in found:
            if url in seen or _skipped(domain, own) or per_domain.get(domain, 0) >= PER_DOMAIN:
                continue
            seen.add(url)
            per_domain[domain] = per_domain.get(domain, 0) + 1
            chosen.append((url, domain))
        return chosen

    @staticmethod
    def _read(
        sources: list[tuple[str, str]], ctx: RunContext
    ) -> tuple[list[FetchedPage], list[str]]:
        pages: list[FetchedPage] = []
        failed: list[str] = []
        for attempt, (url, domain) in enumerate(sources[:MAX_ATTEMPTS]):
            if len(pages) >= MAX_PAGES:
                break
            ctx.progress(
                0.35 + 0.4 * attempt / min(len(sources), MAX_ATTEMPTS),
                f"Reading the top pages: {domain}",
            )
            try:
                page = ctx.pages.fetch(url)
            except PageError:
                failed.append(domain)
                continue
            if page.word_count < MIN_PAGE_WORDS:
                failed.append(domain)
            elif all(p.final_url != page.final_url for p in pages):
                pages.append(page)
        return pages, failed

    @staticmethod
    def _prompt(
        keyword: str,
        searches: list[tuple[str, str]],
        candidates: list[Candidate],
        pages: list[FetchedPage],
        ctx: RunContext,
        country: str,
        language: str,
    ) -> str:
        site = ctx.site
        headings = []
        for page in pages:
            subheadings = [s.heading for s in Document.from_html(page.html).subheadings][:15]
            if subheadings:
                headings.append(f"- {page.domain}: " + "; ".join(subheadings))
        return render(
            "content/content_brief",
            domain=site.domain,
            source_context=site.source_context.strip() or "(not described yet)",
            central_entity=site.central_entity or "(not set)",
            entity_type=site.entity_type or "topic",
            country=country,
            language=language,
            keyword=keyword,
            searches="\n".join(f"- {q} ({e})" for q, e in searches) or "(none found)",
            terms="\n".join(f"- {c.term}: {c.pages}" for c in candidates)
            or "(none: the top pages couldn't be read)",
            page_count=len(pages),
            headings="\n".join(headings) or "(none)",
            term_range="25 to 50" if candidates else "no",
            extra_count=10 if candidates else 35,
        )

    @staticmethod
    def _brief(
        keyword: str,
        plan: BriefPlan,
        candidates: list[Candidate],
        pages: list[FetchedPage],
        blocks: list[list[Block]],
        searches: list[tuple[str, str]],
        country: str,
        language: str,
    ) -> Brief:
        page_words = [p.word_count for p in pages]
        if pages:
            low, high = typical_range(page_words)
            words_min = max(300, low)
            words_max = max(words_min + 200, high)
            # Around the typical page: one very long page shouldn't stretch the range
            typical = median(len(Document.from_html(p.html).subheadings) for p in pages)
            headings_min = max(3, round(typical * 0.75))
            headings_max = max(headings_min + 2, round(typical * 1.25))
        else:
            words_min, words_max = DEFAULT_LENGTH[plan.intent]
            headings_min, headings_max = DEFAULT_HEADINGS
        target_words = (words_min + words_max) // 2
        counters = [PhraseCounter(b.text for b in page_blocks) for page_blocks in blocks]

        def term(text: str, importance: Importance, main: bool = False) -> BriefTerm:
            key = key_of(text)
            per_page = [counter.count(key) for counter in counters]
            using = sum(1 for n in per_page if n)
            if using:
                low, high = Candidate(text, key, using, per_page).target(page_words, target_words)
            elif main:
                low, high = 2, max(3, target_words // 400)
            else:
                low, high = 1, 2
            if main:
                low = max(low, 2)
                high = max(high, low)
            return BriefTerm(
                term=text, importance=importance, min=low, max=high, pages=using, main=main
            )

        terms = [term(keyword, "must", main=True)]
        # Single words of the keyword come with it, so they don't need their own targets
        seen = {key_of(keyword), *((w,) for w in key_of(keyword))}
        known = {c.key: c for c in candidates}
        chosen = [(c.term, c.importance) for c in plan.terms if key_of(c.term) in known]
        if candidates and not chosen:  # Gemini didn't pick from the list: use the best ones
            chosen = [(c.term, "should") for c in candidates[:30]]
        for text, importance in chosen:
            key = key_of(text)
            if key and key not in seen:
                seen.add(key)
                terms.append(term(known[key].term, importance))
        for text in plan.extra_terms:
            text = " ".join(text.lower().split())
            key = key_of(text)
            if key and key not in seen and len(words(text)) <= 4:
                seen.add(key)
                terms.append(term(text, "nice"))
        order = {"must": 0, "should": 1, "nice": 2}
        terms = [terms[0], *sorted(terms[1:], key=lambda t: order[t.importance])][:MAX_TERMS]
        for extra in [t for t in terms[1:] if t.importance == "must"][MAX_MUST - 1 :]:
            extra.importance = "should"

        known_searches = {q for q, _ in searches}
        questions: list[BriefQuestion] = []
        for item in plan.questions:
            heading = " ".join(item.heading.split())
            if heading and heading.lower() not in {q.heading.lower() for q in questions}:
                questions.append(
                    BriefQuestion(
                        heading=heading,
                        searches=[s for s in map(normalize, item.searches) if s in known_searches],
                        what_to_say=item.what_to_say.strip(),
                    )
                )
        if not questions:
            questions = [
                BriefQuestion(heading=q[:1].upper() + q[1:] + "?", searches=[q])
                for q, _ in searches[:8]
            ]

        guide = rules.INTENTS[plan.intent]
        return Brief(
            keyword=keyword,
            country=country,
            language=language,
            reader_wants=guide.label,
            page_type=plan.page_type,
            layout=list(guide.layout),
            title=plan.title.strip(),
            h1=plan.h1.strip(),
            meta_description=plan.meta_description.strip(),
            url_slug=slugify(plan.url_slug or keyword) or slugify(keyword),
            words_min=words_min,
            words_max=words_max,
            headings_min=headings_min,
            headings_max=headings_max,
            terms=terms,
            questions=questions,
            pages=[
                TopPage(
                    url=p.final_url,
                    domain=p.domain,
                    title=p.title or p.h1 or p.domain,
                    word_count=p.word_count,
                    headings=[s.heading for s in Document.from_html(p.html).subheadings][:20],
                )
                for p in pages
            ],
        )

    # --- Output --------------------------------------------------------------------------

    @staticmethod
    def how_often(term: BriefTerm) -> str:
        if term.min == term.max:
            return "once" if term.min == 1 else f"{term.min} times"
        return f"{term.min}–{term.max} times"

    @staticmethod
    def used_by(term: BriefTerm, total: int) -> str:
        return f"{term.pages} of {total} top pages" if term.pages else "Suggested by Gemini"

    def _table(self, brief: Brief) -> pd.DataFrame:
        total = len(brief.pages)
        return pd.DataFrame(
            [
                {
                    "term": t.term,
                    "importance": "Main keyword" if t.main else IMPORTANCE_LABELS[t.importance],
                    "how_often": self.how_often(t),
                    "used_by": self.used_by(t, total),
                }
                for t in brief.terms
            ],
            columns=["term", "importance", "how_often", "used_by"],
        )

    def _report(self, brief: Brief) -> str:
        total = len(brief.pages)
        lines = [
            f"# Writer's brief: “{brief.keyword}”",
            "",
            f"**What the reader wants:** {brief.reader_wants.lower()}  ",
            f"**Kind of page:** {brief.page_type}  ",
            f"**Length:** {brief.words_min:,}–{brief.words_max:,} words, "
            f"with {brief.headings_min}–{brief.headings_max} sections",
            "",
            "## Title and description",
            "",
            f"- [ ] {rules.MAIN_KEYWORD_PLACES[0]}: **{brief.title}**",
            f"- [ ] {rules.MAIN_KEYWORD_PLACES[1]}: **{brief.h1}**",
            f"- [ ] {rules.MAIN_KEYWORD_PLACES[2]}: `/{brief.url_slug}/`",
            f"- [ ] {rules.MAIN_KEYWORD_PLACES[3]}",
            f"- [ ] {rules.MAIN_KEYWORD_PLACES[4]}: {brief.meta_description}".rstrip(": "),
            "",
            "## Sections, in this order",
            "",
        ]
        for n, question in enumerate(brief.questions, 1):
            line = f"{n}. **{question.heading}**"
            if question.what_to_say:
                line += f" — {question.what_to_say}"
            lines.append(line)
        lines += ["", "Under each one: " + " ".join(rules.HEADING_RULES), ""]
        lines += [
            "## Words to use",
            "",
            "| Word or phrase | How often | Used by |",
            "|---|---|---|",
        ]
        for t in brief.terms:
            name = f"**{t.term}** (main keyword)" if t.main else t.term
            lines.append(f"| {name} | {self.how_often(t)} | {self.used_by(t, total)} |")
        lines += ["", f"## Layout for a page to {brief.reader_wants.lower()}", ""]
        lines += [f"- [ ] {item}" for item in brief.layout]
        if brief.pages:
            lines += ["", "## The top pages this is based on", ""]
            lines += [f"- [{p.title}]({p.url}): {p.word_count:,} words" for p in brief.pages]
        return "\n".join(lines).rstrip() + "\n"


# --- Checking a draft's answers --------------------------------------------------------


SECTION_NUMBER = re.compile(r"\b[Ss]ection (\d+)\b")


def _shorten(text: str, limit: int = 300) -> str:
    parts = text.split()
    return " ".join(parts[:limit]) + (" …" if len(parts) > limit else "")


def check_answers(gemini: Gemini, brief: Brief, html: str) -> list[AnswerVerdict]:
    """Ask Gemini whether the draft answers each of the brief's questions, and what to add."""
    doc = Document.from_html(html)
    if doc.word_count < SHORT_DRAFT:
        raise ToolkitError("Write a little more first: there isn't enough text to check yet.")
    sections = doc.sections
    listing = "\n\n".join(
        f"[{n}] {s.heading or 'Introduction'}\n{_shorten(s.text) or '(no text yet)'}"
        for n, s in enumerate(sections, 1)
    )
    questions = "\n".join(
        f"[{n}] {q.heading}" + (f" — {q.what_to_say}" if q.what_to_say else "")
        for n, q in enumerate(brief.questions, 1)
    )
    prompt = render(
        "content/answer_check",
        keyword=brief.keyword,
        country=brief.country,
        language=brief.language,
        questions=questions,
        sections=listing,
    )
    answer = gemini.generate_json(prompt, Verdicts)
    by_number = {v.question: v for v in answer.verdicts}

    def heading(number: int | None) -> str:
        if number is None or not 1 <= number <= len(sections):
            return ""
        return sections[number - 1].heading

    def named(text: str) -> str:
        """Gemini sometimes says "Section 3": the writer sees headings, not numbers."""

        def name(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if not 1 <= number <= len(sections):
                return "another section"
            title = heading(number)
            return f"the section “{title}”" if title else "the introduction"

        return SECTION_NUMBER.sub(name, text.strip())

    result = []
    for n, question in enumerate(brief.questions, 1):
        verdict = by_number.get(n)
        if verdict is None:
            result.append(
                AnswerVerdict(question=question.heading, status="missing", fix=question.what_to_say)
            )
            continue
        answered = verdict.status == "answered"
        missing = verdict.status == "missing"
        place_after = ""
        if missing:
            place_after = (
                "the introduction" if verdict.place_after == 0 else heading(verdict.place_after)
            )
        result.append(
            AnswerVerdict(
                question=question.heading,
                status=verdict.status,
                # For a missing answer, the heading that's there but still empty (if any)
                section=matching_heading(question.heading, doc)
                if missing
                else heading(verdict.section),
                fix="" if answered else named(verdict.fix) or question.what_to_say,
                place_after=place_after,
            )
        )
    return result
