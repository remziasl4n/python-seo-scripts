"""Turn a keyword list into pages: which keywords share a page, and where each one goes.

**How it works**

1. Keywords that mean nearly the same thing to a searcher go on the same page. Google
   treats them as one search, so one strong page does better than several thin ones.
2. On each page, the keyword that best sums up the group becomes the **main keyword**.
   The others become section headings, or get a mention in the text.
3. Gemini works out what the reader wants (to learn, compare, buy or find something),
   the kind of page that serves them best, a title, and an outline in a natural reading
   order. Your site's description and sections (on the Sites page) decide where each page
   lives.
4. Keywords too small for a page of their own become a section on the closest page.
5. Pages are put in order: those tied to what your site sells, with the most keywords and
   the strongest search evidence, come first.

You get a **content plan** (one entry per page, with checklists you can tick off) and a
**keyword table** (where to use every keyword). Choose **How to split pages** to get
fewer, broader pages or more, narrower ones.

The free Gemini plan handles about 100 new keywords a minute; keywords you've used before
come straight from the cache.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic.json_schema import JsonDict
from sklearn.cluster import AgglomerativeClustering

from seo_toolkit.core import writing_rules as rules
from seo_toolkit.core.config import ConfigError, SiteConfig
from seo_toolkit.core.prompts import render
from seo_toolkit.tools.base import RunContext, Tool, ToolResult
from seo_toolkit.tools.research.query_fanout import CONFIRMED, PARTLY, plain_evidence

Split = Literal["broad", "balanced", "narrow"]
SPLIT_LABELS = {
    "broad": "Fewer, broader pages",
    "balanced": "Balanced",
    "narrow": "More, narrower pages",
}
# How alike two keywords must be to share a page, after removing what the whole list has in
# common (see group_keywords). Calibrated on real Gemini embeddings of SEO keyword lists.
THRESHOLDS: dict[str, float] = {"broad": 0.12, "balanced": 0.2, "narrow": 0.3}
# Lists this short have too little in common to remove, so they use plain similarity
SMALL_LIST = 8
SMALL_THRESHOLDS: dict[str, float] = {"broad": 0.93, "balanced": 0.95, "narrow": 0.97}
# A group bigger than this is checked again on its own: next to a broad list, several
# topics can look like one (791 real keywords gave a 311-keyword "page" without this)
MAX_PAGE_KEYWORDS = 30
MAX_RECHECKS = 3
# This alike means the same search, worded differently (centred, or plain for short lists)
SAME_SEARCH = {True: 0.6, False: 0.985}

KEYWORD_COLUMNS = ("keyword", "query", "suggestion")
PAGE_TYPES = rules.PageType
COLUMNS = [
    "keyword",
    "page",
    "priority",
    "use_as",
    "where_to_use_it",
    "heading",
    "reader_wants",
    "page_type",
    "where_on_site",
    "fit",
    "evidence",
]


class KeywordPlannerInputs(BaseModel):
    keywords: list[str] = Field(
        [],
        max_length=1000,
        title="Keywords",
        description="One per line, up to 1,000. Or pick a previous run below.",
    )
    from_run: str | None = Field(
        None,
        title="Or use a previous run",
        description="Use the keywords from a Related searches or Autocomplete run.",
        validate_default=True,
        json_schema_extra={
            "x-widget": "run",
            "x-tools": ["research/query-fanout", "research/autocomplete"],
        },
    )
    split: Split = Field(
        "balanced",
        title="How to split pages",
        description="Fewer pages that each cover more, or more pages that each cover less.",
        json_schema_extra=cast(JsonDict, {"x-labels": SPLIT_LABELS}),
    )

    @field_validator("keywords")
    @classmethod
    def _clean(cls, keywords: list[str]) -> list[str]:
        return list(dict.fromkeys(" ".join(k.lower().split()) for k in keywords if k.strip()))

    @field_validator("from_run")
    @classmethod
    def _need_keywords(cls, from_run: str | None, info: ValidationInfo) -> str | None:
        if not from_run and not info.data.get("keywords"):
            raise ValueError("add keywords above, or pick a previous run to use its keywords")
        return from_run or None


# --- What Gemini returns -------------------------------------------------------------


class KeywordPlacement(BaseModel):
    keyword: str
    use_as: Literal["heading", "text"]
    heading: str = Field("", description="The section heading, as the question people type")


class PagePlan(BaseModel):
    page: int
    main_keyword: str = Field("", description="The page's keyword that best sums up the page")
    same_as: int | None = Field(
        None, description="Another page's id if both would answer the same main question"
    )
    page_name: str
    intent: Literal["learn", "compare", "buy", "find"]
    page_type: PAGE_TYPES
    section: str
    url_slug: str
    title: str
    h1: str
    meta_description: str
    keywords: list[KeywordPlacement]
    split_advice: str = ""


class PagePlans(BaseModel):
    pages: list[PagePlan]


# --- Grouping (pure functions, unit-tested) ------------------------------------------


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return vectors / norms


def comparable(vectors: np.ndarray) -> tuple[np.ndarray, bool]:
    """Vectors to compare keywords with, and whether they were centred.

    Keywords from one topic all look very alike (similarity 0.9+), which hides the
    differences that matter. Removing what the whole list shares (its average) spreads
    them out. Very short lists don't have a meaningful average, so they're left as is.
    """
    if len(vectors) < SMALL_LIST:
        return _unit(vectors), False
    return _unit(vectors - vectors.mean(axis=0)), True


def group_keywords(vectors: np.ndarray, split: Split, depth: int = 0) -> np.ndarray:
    """A group number per keyword: keywords in the same group belong on the same page.

    Oversized groups are grouped again among themselves, where differences that the
    whole list hid become visible.
    """
    if len(vectors) == 1:
        return np.zeros(1, dtype=int)
    points, centred = comparable(vectors)
    threshold = (THRESHOLDS if centred else SMALL_THRESHOLDS)[split]
    model = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=1 - threshold
    )
    labels = model.fit_predict(points)
    if depth >= MAX_RECHECKS:
        return labels
    result = np.empty(len(vectors), dtype=int)
    next_label = 0
    for label in np.unique(labels):
        members = np.flatnonzero(labels == label)
        sub = (
            group_keywords(vectors[members], split, depth + 1)
            if len(members) > MAX_PAGE_KEYWORDS
            else np.zeros(len(members), dtype=int)
        )
        for part in np.unique(sub):
            result[members[sub == part]] = next_label
            next_label += 1
    return result


@dataclass
class Page:
    members: list[int]  # keyword indexes
    main: int = -1
    folded: list[int] = field(default_factory=list)  # small topics added as sections
    score: float = 0.0
    priority: str = ""
    plan: PagePlan | None = None
    duplicate_of: Page | None = None  # another page that would answer the same question

    @property
    def all(self) -> list[int]:
        return self.members + self.folded


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def merge_duplicates(pages: list[Page]) -> tuple[list[Page], list[Page]]:
    """Merge pages that would answer the same question: those Gemini marked as the same,
    and those given the same main heading. Returns (pages, the pages that grew)."""
    position = {id(p): i for i, p in enumerate(pages)}
    parent = list(range(len(pages)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_with_h1: dict[str, int] = {}
    for i, page in enumerate(pages):
        if page.duplicate_of is not None and id(page.duplicate_of) in position:
            parent[root(i)] = root(position[id(page.duplicate_of)])
        h1 = _plain(page.plan.h1) if page.plan else ""
        if h1 in first_with_h1:
            parent[root(i)] = root(first_with_h1[h1])
        elif h1:
            first_with_h1[h1] = i

    groups: dict[int, list[Page]] = {}
    for i, page in enumerate(pages):
        groups.setdefault(root(i), []).append(page)
    kept: list[Page] = []
    grown: list[Page] = []
    for group in groups.values():
        target = max(group, key=lambda p: len(p.all))
        for other in group:
            if other is not target:
                target.members += other.members
                target.folded += other.folded
        target.duplicate_of = None
        kept.append(target)
        if len(group) > 1:
            grown.append(target)
    return kept, grown


def _evidence_bonus(evidence: str) -> float:
    bonus: dict[str, float] = {CONFIRMED: 0.15, PARTLY: 0.05}
    return bonus.get(evidence, 0.0)


def build_pages(
    keywords: list[str], points: np.ndarray, groups: np.ndarray, evidence: list[str]
) -> list[Page]:
    """Pages from groups: pick each main keyword, and fold lone keywords into the closest page."""
    by_group: dict[int, list[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(int(g), []).append(i)
    pages = [Page(members) for members in by_group.values()]
    centres = np.array([points[p.members].mean(axis=0) for p in pages])

    # Lone keywords without outside evidence are too small for a page of their own
    big = [i for i, p in enumerate(pages) if len(p.members) > 1]
    if big:
        for page in pages:
            k = page.members[0]
            if len(page.members) == 1 and evidence[k] != CONFIRMED:
                host = max(big, key=lambda j: float(points[k] @ centres[j]))
                pages[host].folded.append(k)
                page.members = []
        pages = [p for p in pages if p.members]
        centres = np.array([points[p.members].mean(axis=0) for p in pages])

    for page, centre in zip(pages, centres, strict=True):
        page.main = max(
            page.members,
            key=lambda k: (
                float(points[k] @ centre)
                + _evidence_bonus(evidence[k])
                - 0.01 * len(keywords[k].split())
            ),  # prefer the shorter, broader wording
        )
    return pages


def rank_pages(pages: list[Page], evidence: list[str], core_paths: set[str]) -> None:
    """Score and label pages Write first / Next / Later."""
    for page in pages:
        confirmed = sum(evidence[k] == CONFIRMED for k in page.all)
        core = page.plan is not None and page.plan.section in core_paths
        selling = page.plan is not None and page.plan.intent in ("buy", "compare")
        page.score = len(page.all) + 1.5 * confirmed + (3 if core else 0) + (1 if selling else 0)
    ordered = sorted(pages, key=lambda p: -p.score)
    first = max(1, round(len(ordered) * 0.25))
    later = round(len(ordered) * 0.6)
    for rank, page in enumerate(ordered):
        page.priority = rules.PRIORITY_LABELS[0 if rank < first else 1 if rank < later else 2]
    pages.sort(key=lambda p: -p.score)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "page"


# --- The tool ------------------------------------------------------------------------


class KeywordPlanner(Tool):
    name = "keyword-planner"
    group = "planning"
    title = "Keyword planner"
    summary = (
        "Turn a keyword list into pages: which page each keyword belongs on, where to use "
        "it, and how to lay each page out."
    )
    needs = ("gemini_api_key",)
    Inputs = KeywordPlannerInputs

    def run(self, inputs: KeywordPlannerInputs, ctx: RunContext) -> ToolResult:
        keywords, evidence = self._collect(inputs, ctx)
        gemini = ctx.gemini
        notes: list[str] = []
        stage = {"fraction": 0.05, "waited": 0.0}

        def waiting(seconds: float) -> None:
            stage["waited"] += seconds
            ctx.progress(stage["fraction"], f"Waiting {seconds:.0f}s for Gemini's free-plan limit…")

        def embedded(done: int, total: int) -> None:
            stage["fraction"] = 0.05 + 0.55 * done / total
            ctx.progress(stage["fraction"], f"Comparing keywords: {done} of {total}")

        gemini.on_wait = waiting
        ctx.progress(0.02, f"Comparing {len(keywords)} keywords…")
        vectors = gemini.embed(keywords, task="clustering", progress=embedded)
        points, centred = comparable(vectors)
        pages = build_pages(keywords, points, group_keywords(vectors, inputs.split), evidence)

        ctx.progress(0.65, f"Planning {len(pages)} pages…")
        pages = self._plan_pages(pages, keywords, ctx)
        rank_pages(pages, evidence, {s.path for s in ctx.site.sections if s.role == "core"})
        ctx.progress(0.95, "Writing the plan…")

        links = self._links(pages, points, ctx.site)
        table = self._table(pages, keywords, evidence, ctx.site)
        same = SAME_SEARCH[centred]
        report = self._report(pages, keywords, points, links, ctx.site, inputs, same)
        if stage["waited"]:
            notes.append(
                f"Gemini's free plan limits speed: this run waited {stage['waited'] / 60:.0f} "
                "min. Running it again is instant (results are cached)."
            )
        if not ctx.site.source_context.strip():
            notes.append(
                "Your site has no description yet, so pages can't be matched to what you "
                "sell. Add one on the Sites page for better advice."
            )
        ctx.progress(1.0, "Done")
        folded = sum(len(p.folded) for p in pages)
        metrics: dict[str, int | float | str] = {
            "Keywords": len(keywords),
            "Pages": len(pages),
            "Write first": sum(p.priority == rules.PRIORITY_LABELS[0] for p in pages),
            "Added as sections": folded,
        }
        return ToolResult(table, metrics, notes, report)

    # --- Steps ---------------------------------------------------------------------------

    def _collect(
        self, inputs: KeywordPlannerInputs, ctx: RunContext
    ) -> tuple[list[str], list[str]]:
        """Keywords from the form and/or a previous run, with any search evidence they carry."""
        found: dict[str, str] = {k: "" for k in inputs.keywords}
        if inputs.from_run:
            table = ctx.run_table(inputs.from_run)
            column = next((c for c in KEYWORD_COLUMNS if c in table.columns), None)
            if column is None:
                raise ConfigError("That run has no keyword column to use. Pick another run.")
            for _, row in table.iterrows():
                keyword = " ".join(str(row[column]).lower().split())
                if not keyword or keyword == "nan":
                    continue
                if "evidence" in table.columns:
                    level = plain_evidence(str(row["evidence"]))
                elif "times_seen" in table.columns:  # autocomplete: everything was really typed
                    level = CONFIRMED
                else:
                    level = ""
                if not found.get(keyword):
                    found[keyword] = level
        if len(found) > 1000:
            raise ConfigError(
                f"That's {len(found)} keywords; the limit is 1,000 per plan. Use a shorter list."
            )
        return list(found), list(found.values())

    def _plan_pages(self, pages: list[Page], keywords: list[str], ctx: RunContext) -> list[Page]:
        """Plan every page; merge pages that would answer the same question, then re-plan
        just those (two pages for one search would compete with each other in Google)."""
        self._plan(pages, keywords, ctx)
        pages, grown = merge_duplicates(pages)
        if grown:
            ctx.progress(0.9, "Merging pages that answer the same question…")
            self._plan(grown, keywords, ctx)
        return pages

    def _plan(self, pages: list[Page], keywords: list[str], ctx: RunContext) -> None:
        site = ctx.site
        sections = "; ".join(f"{s.path} ({s.name}, {s.role})" for s in site.sections) or "none yet"
        for start in range(0, len(pages), 12):  # a dozen pages per request keeps answers sharp
            batch = pages[start : start + 12]
            listing = "\n".join(
                f'- page {n}: main keyword "{keywords[p.main]}"; other keywords: '
                + (", ".join(f'"{keywords[k]}"' for k in p.all if k != p.main) or "none")
                for n, p in enumerate(batch)
            )
            prompt = render(
                "planning/keyword_planner",
                domain=site.domain,
                source_context=site.source_context.strip() or "(not described yet)",
                central_entity=site.central_entity or "(not set)",
                entity_type=site.entity_type or "topic",
                country=site.country,
                language=site.language,
                sections=sections,
                pages=listing,
            )
            plans = {p.page: p for p in ctx.gemini.generate_json(prompt, PagePlans).pages}
            for n, page in enumerate(batch):
                page.plan = plans.get(n) or self._fallback_plan(n, page, keywords)
                # Same-question links are ids within this batch; keep them as Page objects
                same = page.plan.same_as
                valid = same is not None and 0 <= same < len(batch) and same != n
                page.duplicate_of = batch[same] if valid and same is not None else None
                self._tidy(page, keywords, site)
            ctx.progress(0.65 + 0.25 * min(start + 12, len(pages)) / len(pages), "Planning pages…")

    @staticmethod
    def _fallback_plan(number: int, page: Page, keywords: list[str]) -> PagePlan:
        main = keywords[page.main]
        return PagePlan(
            page=number,
            main_keyword=main,
            same_as=None,
            page_name=main.capitalize(),
            intent="learn",
            page_type="guide",
            section="new",
            url_slug=slugify(main),
            title=main.capitalize(),
            h1=main.capitalize(),
            meta_description="",
            keywords=[],
        )

    @staticmethod
    def _tidy(page: Page, keywords: list[str], site: SiteConfig) -> None:
        """Make Gemini's answer safe to use: every keyword placed once, real paths only."""
        plan = page.plan
        assert plan is not None
        choice = " ".join(plan.main_keyword.lower().split())
        for k in page.members:  # Gemini picks the broadest wording, from this page's own keywords
            if keywords[k] == choice:
                page.main = k
        own = {keywords[k] for k in page.all if k != page.main}
        placed: list[KeywordPlacement] = []
        for item in plan.keywords:
            keyword = " ".join(item.keyword.lower().split())
            if keyword in own and keyword not in {p.keyword for p in placed}:
                heading = item.heading.strip() if item.use_as == "heading" else ""
                placed.append(
                    KeywordPlacement(
                        keyword=keyword, use_as="heading" if heading else "text", heading=heading
                    )
                )
        for k in page.all:  # anything Gemini skipped: folded topics get a heading, others a mention
            keyword = keywords[k]
            if k != page.main and keyword not in {p.keyword for p in placed}:
                folded = k in page.folded
                placed.append(
                    KeywordPlacement(
                        keyword=keyword,
                        use_as="heading" if folded else "text",
                        heading=keyword.capitalize() if folded else "",
                    )
                )
        plan.keywords = placed
        if plan.section not in {s.path for s in site.sections}:
            plan.section = "new"
        plan.url_slug = slugify(plan.url_slug or keywords[page.main])

    @staticmethod
    def _url(plan: PagePlan) -> str:
        base = "/" if plan.section == "new" else plan.section
        return f"{base.rstrip('/')}/{plan.url_slug}/"

    @staticmethod
    def _where(plan: PagePlan, site: SiteConfig) -> str:
        section = next((s for s in site.sections if s.path == plan.section), None)
        return f"{section.path} ({section.name})" if section else "A new part of the site"

    def _links(
        self, pages: list[Page], points: np.ndarray, site: SiteConfig
    ) -> dict[int, list[int]]:
        """For each page, the two most closely related pages that should link to it."""
        if len(pages) < 2:
            return {}
        centres = _unit(np.array([points[p.all].mean(axis=0) for p in pages]))
        similarity = centres @ centres.T
        np.fill_diagonal(similarity, -np.inf)
        return {i: list(np.argsort(-similarity[i])[:2]) for i in range(len(pages))}

    def _table(
        self, pages: list[Page], keywords: list[str], evidence: list[str], site: SiteConfig
    ) -> pd.DataFrame:
        rows = []
        for page in pages:
            plan = page.plan
            assert plan is not None
            guide = rules.INTENTS[plan.intent]
            common = {
                "page": plan.page_name,
                "priority": page.priority,
                "reader_wants": guide.label,
                "page_type": plan.page_type,
                "where_on_site": self._url(plan),
            }
            rows.append(
                {
                    **common,
                    "keyword": keywords[page.main],
                    "use_as": "Main keyword",
                    "where_to_use_it": "Title, main heading (H1), web address, first sentence, "
                    "meta description",
                    "heading": plan.h1,
                    "evidence": evidence[page.main],
                }
            )
            for item in plan.keywords:
                k = keywords.index(item.keyword)
                rows.append(
                    {
                        **common,
                        "keyword": item.keyword,
                        "use_as": "Heading" if item.use_as == "heading" else "In the text",
                        "where_to_use_it": (
                            "As a heading, answered in the first sentence below it"
                            if item.use_as == "heading"
                            else "Once in the text, where it fits naturally"
                        ),
                        "heading": item.heading,
                        "evidence": evidence[k],
                    }
                )
        table = pd.DataFrame(rows)
        table["fit"] = self._fit(table, keywords, pages)
        return table.reindex(columns=COLUMNS).fillna("")

    @staticmethod
    def _fit(table: pd.DataFrame, keywords: list[str], pages: list[Page]) -> list[str]:
        """Strong / Good / Loose: how squarely a keyword belongs on its page."""
        folded = {keywords[k] for p in pages for k in p.folded}
        return [
            "Strong" if use == "Main keyword" else "Loose" if kw in folded else "Good"
            for kw, use in zip(table["keyword"], table["use_as"], strict=True)
        ]

    def _report(
        self,
        pages: list[Page],
        keywords: list[str],
        points: np.ndarray,
        links: dict[int, list[int]],
        site: SiteConfig,
        inputs: KeywordPlannerInputs,
        same_search: float,
    ) -> str:
        total = len(keywords)
        lines = [
            f"# Content plan for {site.domain.removeprefix('https://').removeprefix('http://').rstrip('/')}",
            "",
            f"**{total} keywords → {len(pages)} pages** ({SPLIT_LABELS[inputs.split].lower()}). "
            "Work through the pages in order: **Write first** pages are the ones most tied to "
            "what your site sells, with the most search behind them.",
            "",
            "**On every page**",
            "",
            *[f"- {rule}" for rule in rules.PAGE_RULES],
            "",
        ]
        for number, page in enumerate(pages):
            plan = page.plan
            assert plan is not None
            guide = rules.INTENTS[plan.intent]
            main = keywords[page.main]
            headings: dict[str, list[str]] = {}
            for item in plan.keywords:
                if item.use_as == "heading":
                    headings.setdefault(item.heading, []).append(item.keyword)
            mentions = [item.keyword for item in plan.keywords if item.use_as == "text"]
            lines += [
                "---",
                "",
                f"## {number + 1}. {plan.page_name} · {page.priority}",
                "",
                f"**What the reader wants:** to {guide.reader} ({guide.label.lower()}).  ",
                f"**Kind of page:** {plan.page_type}  ",
                f"**Where it goes:** {self._where(plan, site)}, at `{self._url(plan)}`",
                "",
                f"### Main keyword: “{main}”",
                "",
                "Use it in:",
                "",
                f"- [ ] {rules.MAIN_KEYWORD_PLACES[0]}: **{plan.title}**",
                f"- [ ] {rules.MAIN_KEYWORD_PLACES[1]}: **{plan.h1}**",
                f"- [ ] {rules.MAIN_KEYWORD_PLACES[2]}: `{self._url(plan)}`",
                f"- [ ] {rules.MAIN_KEYWORD_PLACES[3]}",
                f"- [ ] {rules.MAIN_KEYWORD_PLACES[4]}: {plan.meta_description}".rstrip(": "),
                "",
            ]
            if headings:
                lines += ["### Sections, in this order", ""]
                for n, (heading, covered) in enumerate(headings.items(), 1):
                    quoted = ", ".join(f"“{k}”" for k in covered)
                    lines.append(f"{n}. **{heading}** — covers {quoted}")
                lines += ["", "Under each one: " + " ".join(rules.HEADING_RULES), ""]
            if mentions:
                lines += [
                    "**Also mention:** "
                    + ", ".join(f"“{k}”" for k in mentions)
                    + f". {rules.MENTION_RULE}",
                    "",
                ]
            lines += [f"### Layout for a page to {guide.label.lower()}", ""]
            lines += [f"- [ ] {item}" for item in guide.layout]
            lines.append("")
            related = [pages[j] for j in links.get(number, [])]
            if related:
                names = " and ".join(f"**{p.plan.page_name}**" for p in related if p.plan)
                lines += [
                    "### Links",
                    "",
                    f"- [ ] Link to this page from {names}. {rules.LINK_RULE}: “{main}”.",
                    "",
                ]
            same = self._same_search(page, points, keywords, same_search)
            if same:
                lines += [
                    f"> **Same search:** {', '.join(f'“{k}”' for k in same)}. " + rules.SAME_SEARCH,
                    "",
                ]
            if page.folded:
                small = ", ".join(f"“{keywords[k]}”" for k in page.folded)
                lines += [
                    f"> **Added as sections:** {small}. {rules.FOLDED_HERE}",
                    "",
                ]
            if plan.split_advice.strip():
                lines += [f"> **Consider splitting:** {plan.split_advice.strip()}", ""]
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _same_search(
        page: Page, points: np.ndarray, keywords: list[str], threshold: float
    ) -> list[str]:
        """Keywords on the page that are near-identical rewordings of the main keyword."""
        others = [k for k in page.members if k != page.main]
        close = [k for k in others if float(points[k] @ points[page.main]) >= threshold]
        return [keywords[page.main], *(keywords[k] for k in close)] if close else []
