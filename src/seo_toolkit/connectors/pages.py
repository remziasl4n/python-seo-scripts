"""Web pages: fetch one, keep only its main content (no menus, footers or ads).

    fetcher = PageFetcher.from_settings()
    page = fetcher.fetch("https://www.example.com/inground-pool-cost/")
    page.title, page.description, page.h1
    page.html        # the main content as clean HTML (headings, paragraphs, lists, tables)
    page.word_count

Only public websites are read: addresses on this computer or a private network are
refused, including after redirects. Pages are cached like every other request.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from seo_toolkit.core.cache import Cache
from seo_toolkit.core.config import Settings, get_settings
from seo_toolkit.core.content import count_words, parse_html
from seo_toolkit.core.errors import ToolkitError

MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
HTML_TYPES = ("text/html", "application/xhtml+xml")


class PageError(ToolkitError):
    """A page couldn't be read. The message says why, in plain words."""


@dataclass(frozen=True)
class FetchedPage:
    url: str  # what was asked for
    final_url: str  # where it ended up after redirects
    title: str
    description: str
    h1: str
    html: str  # main content only
    word_count: int

    @property
    def domain(self) -> str:
        return (urlsplit(self.final_url).hostname or "").removeprefix("www.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_public(host: str) -> bool:
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False
    for address in addresses:
        ip = ipaddress.ip_address(str(address).split("%")[0])
        if not ip.is_global:
            return False
    return bool(addresses)


def check_address(url: str, is_public: Callable[[str], bool] = _is_public) -> str:
    """The URL, tidied, if it's a public web address; otherwise a PageError."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PageError(f"{url} isn't a web address. Use one like https://www.example.com/page/")
    if not is_public(parts.hostname):
        raise PageError(
            f"{parts.hostname} isn't a public website, so it wasn't read. "
            "Only pages anyone can open on the internet can be used."
        )
    return url


def _inner_body(html: str) -> str:
    body = HTMLParser(html).body
    if body is None:
        return html
    return "".join(child.html or "" for child in body.iter(include_text=False))


def extract_page(html: str, url: str, final_url: str | None = None) -> FetchedPage:
    """The main content of a page's HTML, plus its title, meta description and H1."""
    content = trafilatura.extract(
        html,
        url=final_url or url,
        output_format="html",
        include_formatting=True,
        include_tables=True,
        include_links=False,
        include_images=False,
        include_comments=False,
        favor_recall=True,
    )
    if not content:
        raise PageError(
            f"Couldn't find the main text on {url}. It may be built with scripts. "
            "Paste the text into the editor instead."
        )
    tree = HTMLParser(html)
    meta = trafilatura.extract_metadata(html)
    title = _first_text(tree, "title") or (meta.title if meta and meta.title else "")
    description_tag = tree.css_first('meta[name="description" i]')
    description = (description_tag.attributes.get("content") if description_tag else None) or (
        meta.description if meta and meta.description else ""
    )
    h1 = _first_text(tree, "h1")
    body = _inner_body(content)
    if h1 and not any(block.kind == "heading" and block.level == 1 for block in parse_html(body)):
        body = f"<h1>{_escape(h1)}</h1>{body}"
    return FetchedPage(
        url=url,
        final_url=final_url or url,
        title=" ".join(title.split()),
        description=" ".join(description.split()),
        h1=h1,
        html=body,
        word_count=count_words(body),
    )


def _first_text(tree: HTMLParser, selector: str) -> str:
    node = tree.css_first(selector)
    return " ".join(node.text().split()) if node else ""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class PageFetcher:
    def __init__(
        self,
        http: httpx.Client,
        cache: Cache | None = None,
        delay_seconds: float = 0.5,
        is_public: Callable[[str], bool] = _is_public,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.cache = cache
        self.delay_seconds = delay_seconds
        self.requests = 0
        self.cached = 0
        self._is_public = is_public
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None, refresh: bool = False) -> PageFetcher:
        settings = settings or get_settings()
        http = httpx.Client(
            timeout=settings.crawler_timeout_seconds,
            headers={
                "User-Agent": settings.crawler_user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "en;q=0.9,*;q=0.5",
            },
            follow_redirects=False,  # each hop is checked, see _get
        )
        return cls(
            http,
            cache=Cache.from_settings(settings, refresh=refresh),
            delay_seconds=settings.crawler_delay_seconds,
        )

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            remaining = self.delay_seconds - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def fetch(self, url: str) -> FetchedPage:
        """A page's main content. Raises PageError with a plain explanation if it can't."""
        url = check_address(url, self._is_public)
        key = {"url": url}
        if self.cache is not None:
            stored = self.cache.get("pages", key)
            if stored is not None:
                self.cached += 1
                return FetchedPage(**stored)
        final_url, html = self._get(url)
        page = extract_page(html, url, final_url)
        if self.cache is not None:
            self.cache.set("pages", key, page.to_dict())
        return page

    def _get(self, url: str) -> tuple[str, str]:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._wait_turn()
            try:
                with self.http.stream("GET", current) as response:
                    if response.is_redirect and "location" in response.headers:
                        current = check_address(
                            urljoin(current, response.headers["location"]), self._is_public
                        )
                        continue
                    self._raise_for_status(response, url)
                    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if kind and kind not in HTML_TYPES:
                        raise PageError(f"{url} isn't a web page (it's {kind}).")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise PageError(f"{url} is too big to read (over 5 MB).")
                    encoding = response.encoding or "utf-8"
            except httpx.TimeoutException as e:
                raise PageError(f"{url} took too long to answer.") from e
            except httpx.HTTPError as e:
                raise PageError(f"Couldn't reach {url}: {e}") from e
            self.requests += 1
            return current, bytes(body).decode(encoding, errors="replace")
        raise PageError(f"{url} redirects too many times.")

    @staticmethod
    def _raise_for_status(response: httpx.Response, url: str) -> None:
        code = response.status_code
        if code < 400:
            return
        if code in (401, 403, 429, 503):
            raise PageError(
                f"{urlsplit(url).hostname} blocked the request ({code}). Some sites block "
                "tools: paste the text into the editor instead."
            )
        if code in (404, 410):
            raise PageError(f"Page not found ({code}): {url}. Check the address.")
        raise PageError(f"{url} answered with an error ({code}).")
