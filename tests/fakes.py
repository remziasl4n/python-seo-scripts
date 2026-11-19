"""Fake connectors shared by tool, check and dashboard tests."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
from pydantic import BaseModel

from seo_toolkit.connectors.gemini import GroundedAnswer, Source
from seo_toolkit.connectors.pages import FetchedPage, PageError, extract_page


class FakeGemini:
    """Answers generate_json with `generated`, ground with `searches`, and embeds by hash.

    Texts listed together in `same_meaning` get identical vectors (near-duplicates).
    """

    def __init__(
        self,
        generated: list[dict[str, Any]] | None = None,
        searches: tuple[str, ...] = (),
        same_meaning: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        self.generated = generated or []
        self.searches = searches
        self.same_meaning = same_meaning
        self.grounding = True
        self.on_wait: Any = None
        self.prompts: list[str] = []
        self.ground_calls: list[str] = []
        self.embed_calls: list[list[str]] = []
        # Answers for other schemas, by schema name: data, or a function of the prompt
        self.answers: dict[str, Any] = {}

    def generate_json(self, prompt: str, schema: type[BaseModel], **kwargs: Any) -> BaseModel:
        self.prompts.append(prompt)
        answer = self.answers.get(schema.__name__)
        if answer is not None:
            return schema.model_validate(answer(prompt) if callable(answer) else answer)
        return schema.model_validate({"queries": self.generated})

    def ground(self, prompt: str, **kwargs: Any) -> GroundedAnswer:
        self.ground_calls.append(prompt)
        sources = (Source("a.com", "https://r/1", "a.com"), Source("b.org", "https://r/2", "b.org"))
        return GroundedAnswer("answer", self.searches, sources, (), "fake")

    def _vector(self, text: str) -> np.ndarray:
        for group in self.same_meaning:
            if text in group:
                text = group[0]
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        vector = np.random.default_rng(seed).normal(size=16)
        return vector / np.linalg.norm(vector)

    def embed(self, texts: list[str], task: str = "similarity", **kwargs: Any) -> np.ndarray:
        self.embed_calls.append(list(texts))
        return np.array([self._vector(t) for t in texts])


class DictAutocomplete:
    """Returns the suggestions listed for each query, and nothing otherwise."""

    def __init__(self, suggestions: dict[str, list[str]] | None = None) -> None:
        self.suggestions = suggestions or {}
        self.calls: list[str] = []
        self.requests = 0
        self.cached = 0

    def suggest(self, query: str, country: str = "us", language: str = "en") -> list[str]:
        self.calls.append(query)
        self.requests += 1
        return self.suggestions.get(query, [])


class FakeAutocomplete:
    """Returns three suggestions per query, built from the query text."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.requests = 0
        self.cached = 0
        self.cache = None
        self.fail = fail

    def suggest(self, query: str, country: str = "us", language: str = "en") -> list[str]:
        if self.fail:
            raise self.fail
        self.calls.append((query, country, language))
        self.requests += 1
        # "pool cost calculator" comes back for every variation, so it's the most-seen one
        return [f"{query} texas", "pool cost calculator", f"acme pools {query}"]


class FakePages:
    """Serves pages from {address: HTML} (or {address: (final address, HTML)}); any other
    address is "blocked", like a site that refuses tools."""

    def __init__(self, pages: dict[str, str | tuple[str, str]] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise PageError(f"{url} blocked the request (403).")
        final, html = page if isinstance(page, tuple) else (url, page)
        return extract_page(html, url, final)
