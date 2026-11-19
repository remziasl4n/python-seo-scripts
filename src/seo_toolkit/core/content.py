"""Reading content: headings and paragraphs, words, phrases, and how often each is used.

    blocks = parse_html(html)                # headings and text blocks, in order
    doc = Document.from_html(html)           # sections under each heading, the H1, word count
    counts = PhraseCounter([b.text for b in blocks])
    counts.count("inground pool")            # "Inground pools" counts too

Used to read the top-ranking pages and to score a draft as it's written, so both are
measured the same way.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
# Phrases stop at punctuation: "pool heater. Pool pump" has no "heater pool"
PHRASE_BREAK = re.compile(r"[.!?;:,()\[\]{}|•–—\"“”]+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])")
# Words that can't start or end a useful phrase, on top of the usual English list
STOP_WORDS = frozenset(ENGLISH_STOP_WORDS) | {
    "also", "just", "like", "really", "s", "t", "don", "doesn", "isn", "won", "ll", "ve",
    "re", "d", "m", "use", "used", "using", "make", "makes", "need", "needs", "want",
    "way", "ways", "thing", "things", "lot", "lots", "good", "great", "best", "new",
    "click", "read", "share", "post", "page", "website", "blog", "article", "comment",
    "comments", "reply", "subscribe", "cookie", "cookies", "privacy", "policy", "menu",
}  # fmt: skip
BLOCK_TAGS = "h1, h2, h3, h4, h5, h6, p, li, td, th, blockquote, pre, dt, dd, figcaption"
MAX_PHRASE = 4


@dataclass(frozen=True)
class Block:
    kind: Literal["heading", "text"]
    level: int  # 1-6 for headings, 0 for text
    text: str


def _text(node: Node) -> str:
    return " ".join(node.text(separator=" ").split())


def parse_html(html: str) -> list[Block]:
    """Headings and text blocks in reading order. Nested blocks (a <p> in an <li>) count once."""
    root = HTMLParser(html or "").body
    if root is None:
        return []
    blocks: list[Block] = []
    for node in root.css(BLOCK_TAGS):
        parent = node.parent
        nested = False
        while parent is not None and parent is not root:
            if parent.tag in {"li", "td", "th", "blockquote", "dd", "p"}:
                nested = True
                break
            parent = parent.parent
        if nested:
            continue
        text = _text(node)
        if not text:
            continue
        tag = node.tag or ""
        if tag[:1] == "h" and tag[1:].isdigit():
            blocks.append(Block("heading", int(tag[1:]), text))
        else:
            blocks.append(Block("text", 0, text))
    return blocks


def words(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in WORD.findall(text)]


def count_words(html_or_blocks: str | Sequence[Block]) -> int:
    blocks = parse_html(html_or_blocks) if isinstance(html_or_blocks, str) else html_or_blocks
    return sum(len(words(b.text)) for b in blocks)


def stem(word: str) -> str:
    """Fold English plurals and possessives, so "pools" and "pool's" count as "pool"."""
    word = word.lower().removesuffix("'s").removesuffix("'")
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is", "os")):
        return word[:-1]
    return word


def chunks(text: str) -> list[str]:
    """Pieces of text between punctuation marks, which phrases never cross."""
    return [piece for piece in PHRASE_BREAK.split(text) if piece.strip()]


def key_of(phrase: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in words(phrase))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text) if s.strip()]


class PhraseCounter:
    """How often each word or phrase (up to four words) appears, ignoring plurals.

    Phrases never run across blocks or punctuation, so a heading and the paragraph under
    it don't join up, and neither do two sentences.
    """

    def __init__(self, texts: Iterable[str]) -> None:
        self.counts: Counter[tuple[str, ...]] = Counter()
        for piece in (piece for text in texts for piece in chunks(text)):
            keys = [stem(w) for w in words(piece)]
            for n in range(1, MAX_PHRASE + 1):
                for i in range(len(keys) - n + 1):
                    self.counts[tuple(keys[i : i + n])] += 1

    def count(self, phrase: str | tuple[str, ...]) -> int:
        key = key_of(phrase) if isinstance(phrase, str) else phrase
        return self.counts.get(key, 0) if key else 0


# --- A document, as sections -----------------------------------------------------------


@dataclass
class Section:
    heading: str  # "" for the text before the first heading
    level: int
    paragraphs: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.paragraphs)

    @property
    def word_count(self) -> int:
        return len(words(self.text))

    @property
    def first_sentence(self) -> str:
        found = sentences(self.paragraphs[0]) if self.paragraphs else []
        return found[0] if found else ""


@dataclass
class Document:
    blocks: list[Block]
    sections: list[Section]

    @classmethod
    def from_html(cls, html: str) -> Document:
        blocks = parse_html(html)
        sections = [Section("", 0)]
        for block in blocks:
            if block.kind == "heading":
                sections.append(Section(block.text, block.level))
            else:
                sections[-1].paragraphs.append(block.text)
        if not sections[0].paragraphs and len(sections) > 1:
            sections = sections[1:]
        return cls(blocks, sections)

    @property
    def h1s(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "heading" and b.level == 1]

    @property
    def subheadings(self) -> list[Section]:
        return [s for s in self.sections if s.level >= 2]

    @property
    def intro(self) -> Section | None:
        """The first section with text: under the H1, or before any heading."""
        return next((s for s in self.sections if s.level <= 1 and s.paragraphs), None)

    @property
    def word_count(self) -> int:
        return count_words(self.blocks)

    def counter(self) -> PhraseCounter:
        return PhraseCounter(b.text for b in self.blocks)


# --- Words the top pages share ---------------------------------------------------------


@dataclass
class Candidate:
    """A word or phrase used across the top pages, with how much each page uses it."""

    term: str  # the most common way it's written
    key: tuple[str, ...]
    pages: int  # how many pages use it
    per_page: list[int]  # times used on each page (0 if not)
    score: float = 0.0

    def target(self, page_words: Sequence[int], target_words: int) -> tuple[int, int]:
        """How many times to use it in a page of `target_words`, from the pages that use it."""
        rates = sorted(
            count / max(words_, 1) * target_words
            for count, words_ in zip(self.per_page, page_words, strict=True)
            if count
        )
        if not rates:
            return 1, 2
        low = rates[max(0, math.ceil(len(rates) * 0.25) - 1)]
        high = rates[min(len(rates) - 1, math.ceil(len(rates) * 0.75) - 1)]
        least = max(1, round(low))
        return least, max(least, round(high))


def _usable(gram: Sequence[str]) -> bool:
    if gram[0] in STOP_WORDS or gram[-1] in STOP_WORDS:
        return False
    if any(w.isdigit() for w in (gram[0], gram[-1])):
        return False
    return not (len(gram) == 1 and len(gram[0]) < 3)


def shared_terms(pages: Sequence[Sequence[Block]], limit: int = 120) -> list[Candidate]:
    """Words and phrases (one to three words) that several of the pages use, best first.

    A term counts if at least 30% of pages use it (at least two, when there are two or
    more pages). Terms used on more pages, more often, and longer phrases rank higher.
    A word that almost only appears inside a longer kept phrase is dropped, so the list
    has "inground pool" without a separate "inground".
    """
    total = len(pages)
    if total == 0:
        return []
    per_page: list[Counter[tuple[str, ...]]] = []
    spellings: dict[tuple[str, ...], Counter[str]] = {}
    for blocks in pages:
        counts: Counter[tuple[str, ...]] = Counter()
        for piece in (piece for block in blocks for piece in chunks(block.text)):
            raw = words(piece)
            keys = [stem(w) for w in raw]
            for n in range(1, 4):
                for i in range(len(raw) - n + 1):
                    gram = raw[i : i + n]
                    if not _usable(gram):
                        continue
                    key = tuple(keys[i : i + n])
                    counts[key] += 1
                    spellings.setdefault(key, Counter())[" ".join(gram)] += 1
        per_page.append(counts)

    needed = 1 if total == 1 else max(2, math.ceil(total * 0.3))
    found: Counter[tuple[str, ...]] = Counter()
    for counts in per_page:
        found.update(counts.keys())
    candidates: dict[tuple[str, ...], Candidate] = {}
    for key, pages_using in found.items():
        uses = [counts.get(key, 0) for counts in per_page]
        if pages_using < needed or (total == 1 and uses[0] < 2):
            continue
        typical = median([u for u in uses if u])
        score = (pages_using / total) * (1 + math.log1p(typical)) * (1 + 0.35 * (len(key) - 1))
        term = spellings[key].most_common(1)[0][0]
        candidates[key] = Candidate(term, key, pages_using, uses, score)

    # Drop words and short phrases that are nearly always part of a longer kept phrase
    totals = {key: sum(c.per_page) for key, c in candidates.items()}
    for key in sorted(candidates, key=len, reverse=True):
        if len(key) == 1 or key not in candidates:
            continue
        for n in range(1, len(key)):
            for i in range(len(key) - n + 1):
                part = key[i : i + n]
                if part in candidates and totals[part] <= 1.2 * totals[key]:
                    del candidates[part]
    return sorted(candidates.values(), key=lambda c: -c.score)[:limit]


def typical_range(values: Sequence[int], step: int = 50) -> tuple[int, int]:
    """The middle half of `values` (25th to 75th percentile), rounded to `step`."""
    ordered = sorted(values)
    if not ordered:
        return 0, 0
    low = ordered[max(0, math.ceil(len(ordered) * 0.25) - 1)]
    high = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.75) - 1)]

    def rounded(value: float) -> int:
        return round(value / step) * step if step > 1 else round(value)

    return rounded(low), max(rounded(low), rounded(high))
