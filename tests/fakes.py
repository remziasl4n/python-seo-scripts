"""Fake connectors shared by tool, check and dashboard tests."""

from __future__ import annotations


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
