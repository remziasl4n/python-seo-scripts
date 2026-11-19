"""Reading web pages, with a fake network: no real requests."""

import httpx
import pytest

from seo_toolkit.connectors.pages import PageError, PageFetcher, check_address, extract_page
from seo_toolkit.core.cache import Cache

ARTICLE = """
<html><head><title>Inground Pool Cost (2026) | Acme</title>
<meta name="description" content="What an inground pool really costs."></head>
<body><nav><a href="/">Home</a> <a href="/about">About us</a></nav>
<main><h1>Inground pool cost</h1>
<p>An inground pool costs about $65,000 in 2026 for most homes, depending on the size,
the shape and the material you pick. Prices rise a little every year as labour gets dearer.</p>
<h2>How much is a fiberglass pool?</h2>
<p>A fiberglass pool costs $45,000 to $85,000 installed, including the shell, the dig and
the patio around it. Most installs take two to three weeks from the first dig.</p>
<h2>What does upkeep cost?</h2>
<p>Plan on about $1,200 a year for chemicals, power and small repairs for a family pool.</p>
</main><footer>Copyright 2026 Acme Pools. All rights reserved.</footer></body></html>
"""

PUBLIC = {"www.example.com", "example.com", "pools.example.org"}


def is_public(host: str) -> bool:
    return host in PUBLIC


def fetcher(handler, cache=None) -> PageFetcher:
    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return PageFetcher(http, cache=cache, delay_seconds=0, is_public=is_public)


def test_main_content_only_with_title_description_and_h1():
    page = extract_page(ARTICLE, "https://www.example.com/cost/")
    assert page.title.startswith("Inground Pool Cost (2026)")
    assert page.description == "What an inground pool really costs."
    assert page.h1 == "Inground pool cost"
    assert "<h2>How much is a fiberglass pool?</h2>" in page.html
    assert "About us" not in page.html and "All rights reserved" not in page.html
    assert 70 < page.word_count < 110
    assert page.domain == "example.com"


def test_addresses_are_tidied_and_private_ones_refused():
    assert check_address("www.example.com/cost/", is_public) == "https://www.example.com/cost/"
    with pytest.raises(PageError, match="isn't a public website"):
        check_address("http://localhost:8000/api/sites", is_public)
    with pytest.raises(PageError, match="isn't a web address"):
        check_address("ftp://www.example.com/file", is_public)


def test_real_lookup_refuses_this_computer():
    with pytest.raises(PageError, match="isn't a public website"):
        check_address("http://127.0.0.1/")


def test_redirects_are_followed_and_each_hop_checked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://pools.example.org/cost/"})
        if request.url.path == "/sneaky":
            return httpx.Response(302, headers={"location": "http://localhost/admin"})
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})

    pages = fetcher(handler)
    page = pages.fetch("https://www.example.com/old")
    assert page.final_url == "https://pools.example.org/cost/"
    assert page.url == "https://www.example.com/old"
    with pytest.raises(PageError, match="isn't a public website"):
        pages.fetch("https://www.example.com/sneaky")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403), "blocked the request"),
        (httpx.Response(404), "Page not found"),
        (httpx.Response(500), "answered with an error"),
        (
            httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
            "isn't a web page",
        ),
        (
            httpx.Response(
                200, text="<html><body></body></html>", headers={"content-type": "text/html"}
            ),
            "main text",
        ),
    ],
)
def test_problems_are_explained(response, message):
    with pytest.raises(PageError, match=message):
        fetcher(lambda request: response).fetch("https://www.example.com/page")


def test_pages_are_cached(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})

    cache = Cache(tmp_path)
    first = fetcher(handler, cache).fetch("https://www.example.com/cost/")
    again = fetcher(handler, cache)
    assert again.fetch("https://www.example.com/cost/") == first
    assert len(calls) == 1 and again.cached == 1
