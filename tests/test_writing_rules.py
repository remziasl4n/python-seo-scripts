"""The plain-English rules every writing tool shows: no SEO jargon anywhere in them."""

import re

from seo_toolkit.core import writing_rules as rules


def test_no_rule_contains_jargon():
    texts = [
        *rules.MAIN_KEYWORD_PLACES,
        *rules.HEADING_RULES,
        *rules.PAGE_RULES,
        rules.MENTION_RULE,
        rules.LINK_RULE,
        rules.FOLDED_HERE,
        rules.SAME_SEARCH,
        *rules.PRIORITY_LABELS,
        *rules.CHECKS.values(),
        *rules.TIPS.values(),
        *(label for _, label in rules.SCORE_LABELS),
        *(
            guide.label + " " + guide.reader + " " + " ".join(guide.layout)
            for guide in rules.INTENTS.values()
        ),
    ]
    text = "\n".join(texts).lower()
    assert [w for w in rules.JARGON if re.search(rf"\b{re.escape(w)}\b", text)] == []


def test_every_search_intent_has_a_guide():
    assert set(rules.SEARCH_INTENTS.values()) == set(rules.INTENTS)
