"""Google autocomplete suggestions, from the public suggest endpoint browsers use.

    client = AutocompleteClient.from_settings()
    client.suggest("pool cost", country="us", language="en")   # ["pool cost calculator", ...]

Free and needs no key, but it's unofficial: requests are spaced out by
CRAWLER_DELAY_SECONDS and every answer is cached, so reruns don't hit Google again.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx

from seo_toolkit.core.cache import Cache
from seo_toolkit.core.config import Settings, get_settings
from seo_toolkit.core.errors import ToolkitError

URL = "https://suggestqueries.google.com/complete/search"


class AutocompleteError(ToolkitError):
    """An autocomplete request failed. The message says what to try."""


class AutocompleteClient:
    def __init__(
        self,
        http: httpx.Client,
        cache: Cache | None = None,
        delay_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.cache = cache
        self.delay_seconds = delay_seconds
        self.requests = 0
        self.cached = 0
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, refresh: bool = False
    ) -> AutocompleteClient:
        settings = settings or get_settings()
        http = httpx.Client(
            timeout=settings.crawler_timeout_seconds,
            headers={"User-Agent": settings.crawler_user_agent},
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

    def suggest(self, query: str, country: str = "us", language: str = "en") -> list[str]:
        """Google's suggestions for `query`, in the order Google ranks them."""
        key = {"q": query, "gl": country, "hl": language}
        if self.cache is not None:
            stored = self.cache.get("autocomplete", key)
            if stored is not None:
                self.cached += 1
                return list(stored)

        self._wait_turn()
        params = {"client": "firefox", "ie": "utf-8", "oe": "utf-8", **key}
        try:
            response = self.http.get(URL, params=params)
            response.raise_for_status()
            data = json.loads(response.text)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 429, 503):
                raise AutocompleteError(
                    "Google is limiting autocomplete requests. Wait a few minutes, "
                    "or raise CRAWLER_DELAY_SECONDS in .env."
                ) from e
            raise AutocompleteError(f"Autocomplete request failed: {e}") from e
        except httpx.HTTPError as e:
            raise AutocompleteError(f"Couldn't reach Google autocomplete: {e}") from e
        except json.JSONDecodeError as e:
            raise AutocompleteError(
                "Google autocomplete returned something other than JSON."
            ) from e
        self.requests += 1

        # The response looks like ["pool cost", ["pool cost calculator", ...], ...]
        if not (isinstance(data, list) and len(data) > 1 and isinstance(data[1], list)):
            raise AutocompleteError("Google autocomplete returned an unexpected format.")
        suggestions = [s for s in data[1] if isinstance(s, str)]

        if self.cache is not None:
            self.cache.set("autocomplete", key, suggestions)
        return suggestions
