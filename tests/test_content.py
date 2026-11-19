import pytest

from seo_toolkit.core.content import (
    Block,
    Candidate,
    Document,
    PhraseCounter,
    count_words,
    parse_html,
    sentences,
    shared_terms,
    stem,
    typical_range,
)

DRAFT = """
<h1>Inground pool cost</h1>
<p>An inground pool costs about $65,000. Prices vary by state.</p>
<h2>How much is a fiberglass pool?</h2>
<p>A fiberglass pool costs $45,000 to $85,000.</p>
<ul><li><p>Shell and delivery</p></li><li>Labour <b>and</b> digging</li></ul>
<h2>Running costs</h2>
<h3>Chemicals</h3>
<p>About $600 a year.</p>
"""


def test_blocks_come_in_reading_order_and_nested_blocks_count_once():
    blocks = parse_html(DRAFT)
    assert blocks[0] == Block("heading", 1, "Inground pool cost")
    assert [b.text for b in blocks if b.kind == "text"] == [
        "An inground pool costs about $65,000. Prices vary by state.",
        "A fiberglass pool costs $45,000 to $85,000.",
        "Shell and delivery",
        "Labour and digging",
        "About $600 a year.",
    ]
    assert parse_html("") == []


def test_document_sections():
    doc = Document.from_html(DRAFT)
    assert doc.h1s == ["Inground pool cost"]
    assert (
        doc.intro is not None
        and doc.intro.first_sentence == "An inground pool costs about $65,000."
    )
    assert [s.heading for s in doc.subheadings] == [
        "How much is a fiberglass pool?",
        "Running costs",
        "Chemicals",
    ]
    fiberglass = doc.subheadings[0]
    assert fiberglass.paragraphs[1:] == ["Shell and delivery", "Labour and digging"]
    assert doc.word_count == count_words(DRAFT)


@pytest.mark.parametrize(
    ("word", "folded"),
    [
        ("pools", "pool"),
        ("pool's", "pool"),
        ("batteries", "battery"),
        ("boxes", "box"),
        ("glass", "glass"),
        ("bus", "bus"),
        ("costs", "cost"),
        ("2026", "2026"),
    ],
)
def test_plurals_and_possessives_fold(word, folded):
    assert stem(word) == folded


def test_phrases_are_counted_ignoring_plurals_but_not_across_blocks():
    counter = PhraseCounter(["Inground pools are popular.", "An inground pool costs more", "pool"])
    assert counter.count("inground pool") == 2
    assert counter.count("Inground Pools") == 2
    assert counter.count("pool costs") == 1
    assert counter.count("popular inground") == 0  # "popular." and "An inground" are apart
    assert counter.count("") == 0


def test_sentences():
    assert sentences("It costs $5. Then more! Is it? yes") == [
        "It costs $5.",
        "Then more!",
        "Is it? yes",
    ]


def page(*texts: str) -> list[Block]:
    return [Block("text", 0, text) for text in texts]


def test_shared_terms_need_several_pages_and_skip_filler():
    pages = [
        page("The fiberglass pool cost is high.", "Fiberglass pools last long."),
        page("Our fiberglass pool cost guide.", "Check the warranty."),
        page("A fiberglass pool is quick to install.", "Warranty terms vary."),
        page("Concrete takes longer to build."),
    ]
    terms = {c.term: c for c in shared_terms(pages)}
    assert terms["fiberglass pool cost"].pages == 2
    assert terms["warranty"].pages == 2
    assert "concrete" not in terms  # one page only
    assert "the" not in terms and "is" not in terms
    # "fiberglass" alone is almost always part of "fiberglass pool", so only the phrase is kept
    assert "fiberglass pool" in terms and "fiberglass" not in terms


def test_a_single_page_needs_repeats():
    terms = {c.term for c in shared_terms([page("Pool heater. Pool heater. Pool pump.")])}
    assert "pool heater" in terms and "pool pump" not in terms


def test_targets_scale_to_the_planned_length():
    candidate = Candidate("pool", ("pool",), pages=3, per_page=[10, 20, 0, 30])
    # Pages of 1,000 words using it 10, 20 and 30 times: in a 500-word page, 5 to 15 times
    assert candidate.target([1000, 1000, 1000, 1000], 500) == (5, 15)
    unused = Candidate("x", ("x",), pages=0, per_page=[0, 0])
    assert unused.target([100, 100], 1000) == (1, 2)


def test_typical_range():
    assert typical_range([900, 1200, 1500, 2600, 4000]) == (1200, 2600)
    assert typical_range([4, 9, 12, 30], step=1) == (4, 12)
    assert typical_range([]) == (0, 0)
