"""Content rules in plain English, for every tool that tells people what to write.

Each rule comes from docs/semantic-seo-principles.md, but is worded for a writer, not an
SEO specialist: no "macro context", "entities" or "query fan-out". A test fails if jargon
creeps into anything here (see tests/test_writing_rules.py).

    INTENTS["compare"].label        -> "Compare options"
    INTENTS["compare"].layout       -> what a comparison page needs, as a checklist
    MAIN_KEYWORD_PLACES             -> where a page's main keyword goes
    CHECKS, TIPS                    -> the content editor's checklist, and how to fix each item
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Intent = Literal["learn", "compare", "buy", "find"]
PageType = Literal[
    "guide",
    "how-to guide",
    "comparison",
    "list of options",
    "product or service page",
    "pricing page",
    "location page",
    "FAQ page",
]


@dataclass(frozen=True)
class IntentGuide:
    label: str  # shown to users
    reader: str  # what the searcher wants, completing "The reader wants to …"
    layout: tuple[str, ...]  # checklist for a page with this purpose


INTENTS: dict[str, IntentGuide] = {
    "learn": IntentGuide(
        label="Learn",
        reader="understand something or find out how to do it",
        layout=(
            "Answer the main question in the first two sentences, before any background.",
            "Use the questions people ask as your headings.",
            "Use numbered steps for anything done in order, and bullet points for lists.",
            "Finish with a short FAQ for the smaller questions.",
        ),
    ),
    "compare": IntentGuide(
        label="Compare options",
        reader="weigh up options before deciding",
        layout=(
            "Put a comparison table near the top: options down the side, what matters "
            "(price, lifespan, upkeep…) across.",
            "Give a clear recommendation: which option suits which kind of person.",
            "Add pros and cons for each option.",
            "Link to each option's own page for the full details.",
        ),
    ),
    "buy": IntentGuide(
        label="Buy or hire",
        reader="buy, book or get a quote",
        layout=(
            "Show the offer (price or 'get a quote') and the main button near the top.",
            "Add proof you can be trusted: reviews, guarantees, licences, photos of real work.",
            "Answer the usual worries in short sections: cost, timing, warranty, "
            "what happens next.",
            "Keep it focused: link to your guides for the long explanations.",
        ),
    ),
    "find": IntentGuide(
        label="Find a specific place or brand",
        reader="reach a particular business, brand or location",
        layout=(
            "Put the name, address, phone number and opening hours where they're seen first.",
            "Add a map and directions if people visit in person.",
            "Link straight to the most-wanted pages (contact, prices, booking).",
        ),
    ),
}

# Search intent names Gemini answers with, mapped to the guides above
SEARCH_INTENTS: dict[str, str] = {
    "informational": "learn",
    "commercial": "compare",
    "transactional": "buy",
    "navigational": "find",
}

# Where a page's main keyword goes, in order of importance
MAIN_KEYWORD_PLACES: tuple[str, ...] = (
    "Page title (the blue link in Google), near the start",
    "Main heading (H1)",
    "Web address (URL)",
    "First sentence of the introduction",
    "Meta description (the text under the link in Google)",
)

# Under every question heading
HEADING_RULES: tuple[str, ...] = (
    "Answer the question in the first sentence underneath, in about 40 words.",
    "Start that sentence with the words of the heading, so the answer stands on its own.",
    "Then add the detail: numbers, examples, steps.",
)

# For keywords that don't get their own heading
MENTION_RULE = "Use it once, where it fits naturally. Don't force it in."

# For every page
PAGE_RULES: tuple[str, ...] = (
    "Keep the whole page about one topic; save side topics for their own pages and link to them.",
    "Use exact numbers, dates and named sources instead of 'many', 'several' or 'a lot'.",
    "Keep sales buttons and banners out of the middle of an answer.",
    "Make each section lead into the next: what it is, the details, the comparisons, "
    "the costs, how to do it, what to do next.",
)

LINK_RULE = "Use this page's main keyword as the link text"

FOLDED_HERE = "Too small for pages of their own, so they're covered as sections on this page."

SAME_SEARCH = (
    "These are the same search worded differently. Don't make a page for each: they would "
    "compete with each other in Google. Use one as a heading and the others in the text."
)

PRIORITY_LABELS = ("Write first", "Next", "Later")

# --- The content editor's checklist ----------------------------------------------------
# {heading}, {word} and {n} are filled in by core/editor.py.

TITLE_LENGTH = (30, 60)  # characters Google shows in full
META_LENGTH = (120, 160)
ANSWER_WORDS = 50  # a first sentence longer than this isn't a quick answer
LONG_PARAGRAPH = 120  # words
VAGUE_WORDS = ("many", "several", "a lot of", "lots of", "various", "numerous", "a number of")
# A first word that leans on the sentence before it, so the answer can't stand on its own
LEANING_WORDS = ("it", "this", "that", "these", "those", "they", "he", "she")

CHECKS = {
    "keyword_title": "Main keyword in the page title",
    "keyword_h1": "Main keyword in the main heading (H1)",
    "keyword_url": "Main keyword in the web address",
    "keyword_intro": "Main keyword in the first sentence",
    "keyword_meta": "Main keyword in the meta description",
    "title_length": "Page title is 30–60 characters",
    "meta_length": "Meta description is 120–160 characters",
    "one_h1": "One main heading (H1) at the top",
    "answers_first": "Every question heading is answered in the first sentence",
    "answers_stand_alone": "Every answer makes sense on its own",
    "short_paragraphs": "Paragraphs are short and easy to scan",
    "exact_numbers": "Exact numbers instead of vague words",
    "no_empty_sections": "Every heading has text under it",
}

TIPS = {
    "keyword_title": "Put “{keyword}” near the start of the page title.",
    "keyword_h1": "Use “{keyword}” in the main heading at the top of the page.",
    "keyword_url": "Put the main keyword in the web address, e.g. /{slug}/.",
    "keyword_intro": "Use “{keyword}” in the first sentence, and answer it straight away.",
    "keyword_meta": "Use “{keyword}” in the meta description (the text under the link in Google).",
    "title_short": "The title is {n} characters. Add detail until it's at least 30.",
    "title_long": "The title is {n} characters, so Google will cut it off. Keep it under 60.",
    "meta_short": "The meta description is {n} characters. Aim for 120–160.",
    "meta_long": "The meta description is {n} characters, so Google will cut it off. "
    "Keep it under 160.",
    "meta_missing": "Write a meta description: one or two sentences saying what the page answers.",
    "no_h1": "Add a main heading (H1) at the top of the page.",
    "many_h1": "There are {n} main headings (H1). Keep one, and make the others H2.",
    "answer_first": "Under “{heading}”, answer the question in the first sentence "
    "(about 40 words), then add the detail.",
    "stand_alone": "Under “{heading}”, start with the subject instead of “{word}”, so the "
    "answer makes sense on its own.",
    "long_paragraph": "Under “{heading}”, a paragraph is {n} words long. Split it, or use a list.",
    "vague": "Under “{heading}”, replace “{word}” with an exact number.",
    "empty_section": "“{heading}” has no text under it yet.",
}

SCORE_LABELS = ((85, "Great"), (65, "Good"), (40, "Getting there"), (0, "Needs work"))

# Shown to users anywhere they could see jargon; tests check none of these appear
JARGON = (
    "macro context",
    "micro context",
    "contextual",
    "entity",
    "entities",
    "fan-out",
    "fanout",
    "semantic",
    "embedding",
    "centroid",
    "cluster",
    "topical",
    "eav",
    "cannibal",
)
