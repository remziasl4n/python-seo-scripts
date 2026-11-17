"""Setup checks, shared by `seo doctor` and the dashboard's Setup page.

`config_checks` only reads files. `live_checks` makes one small real call to each
configured API (one Gemini text call, one embedding, one grounded search, one
autocomplete request), bypassing the cache.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from seo_toolkit.core.config import Settings
from seo_toolkit.core.db import is_ready
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.sites import load_site

Status = Literal["ok", "warn", "fail", "off"]
ICONS: dict[str, str] = {"ok": "✅", "warn": "⚠️", "fail": "❌", "off": "⚪"}


@dataclass(frozen=True)
class Check:
    area: str
    name: str
    status: Status
    detail: str


# (setting, label, what it unlocks)
KEYS: tuple[tuple[str, str, str], ...] = (
    ("gemini_api_key", "GEMINI_API_KEY", "query fan-out, clustering, content analysis"),
    ("google_api_key", "GOOGLE_API_KEY", "Knowledge Graph, PageSpeed, Natural Language"),
    ("google_application_credentials", "GOOGLE_APPLICATION_CREDENTIALS", "Search Console, GA4"),
    ("dataforseo_login", "DATAFORSEO_LOGIN", "SERP data and search volumes (paid)"),
    ("serpapi_api_key", "SERPAPI_API_KEY", "SERP data (paid)"),
)


def config_checks(settings: Settings, site_name: str | None = None) -> list[Check]:
    checks = []

    env_file = settings.project_dir / ".env"
    if env_file.is_file():
        checks.append(Check("Settings", ".env file", "ok", str(env_file)))
    else:
        checks.append(
            Check("Settings", ".env file", "warn", "Not found. Run `cp .env.example .env`.")
        )

    ready, detail = is_ready(settings)
    checks.append(Check("Settings", "Database", "ok" if ready else "fail", detail))

    if not ready:
        checks.append(Check("Site", "Site", "off", "Needs the database."))
    else:
        try:
            site = load_site(site_name, settings)
        except ToolkitError as e:
            checks.append(Check("Site", "Site", "fail", str(e)))
        else:
            checks.append(Check("Site", "Site", "ok", f"{site.name}: {site.domain}"))
            if site.name == "example":
                checks.append(
                    Check(
                        "Site",
                        "Your own site",
                        "warn",
                        "Using the example site. Add your own on the Sites page.",
                    )
                )
            empty = [
                f for f in ("source_context", "central_entity") if not getattr(site, f).strip()
            ]
            if empty:
                checks.append(
                    Check(
                        "Site",
                        "Semantic context",
                        "warn",
                        f"{', '.join(empty)} empty: planning tools need them.",
                    )
                )
            else:
                checks.append(Check("Site", "Semantic context", "ok", site.central_entity))

    for setting, label, unlocks in KEYS:
        value = getattr(settings, setting)
        if value is None:
            checks.append(Check("Keys", label, "off", f"Not set. Unlocks: {unlocks}."))
        elif setting == "google_application_credentials" and not settings.resolve(value).is_file():
            checks.append(
                Check("Keys", label, "fail", f"File not found: {settings.resolve(value)}")
            )
        else:
            checks.append(Check("Keys", label, "ok", f"Set. Unlocks: {unlocks}."))
    return checks


def _attempt(area: str, name: str, call: Callable[[], str]) -> Check:
    try:
        return Check(area, name, "ok", call())
    except ToolkitError as e:
        return Check(area, name, "fail", str(e))


LIVE_TIMEOUT_SECONDS = 30


def _no_step(message: str) -> None:
    pass


def live_checks(
    settings: Settings,
    gemini: Any | None = None,
    autocomplete: Any | None = None,
    on_step: Callable[[str], None] = _no_step,
) -> list[Check]:
    """Real calls to each configured API, one attempt each, so a problem shows up fast.

    `on_step` is told which check is running. `gemini` / `autocomplete` let tests pass fakes.
    """
    from seo_toolkit.connectors.autocomplete import AutocompleteClient
    from seo_toolkit.connectors.gemini import Gemini, GeminiError

    checks = []
    if gemini is None and settings.gemini_api_key is None:
        checks.append(Check("Gemini", "Connection", "off", "Add GEMINI_API_KEY to test Gemini."))
    else:
        try:
            gemini = gemini or Gemini.from_settings(
                settings, max_attempts=1, timeout_seconds=LIVE_TIMEOUT_SECONDS
            )
        except ToolkitError as e:
            checks.append(Check("Gemini", "Connection", "fail", str(e)))
            gemini = None

    if gemini is not None:
        gemini.cache = None  # a live check must reach the API

        def text() -> str:
            reply = gemini.generate("Reply with the single word OK.")
            return f"{gemini.model} replied “{reply.strip()[:40]}”"

        def embedding() -> str:
            vectors = gemini.embed(["swimming pool"])
            return f"{gemini.embedding_model}: {vectors.shape[1]} dimensions"

        def grounding() -> str:
            # A question only a search can answer, so the check proves searching works
            answer = gemini.ground("What are today's top news headlines? One line.")
            if not answer.search_queries:
                raise GeminiError(f"{gemini.grounding_model} answered without searching Google.")
            return (
                f"{gemini.grounding_model} ran {len(answer.search_queries)} Google search(es), "
                f"{len(answer.sources)} sources"
            )

        on_step(f"Gemini text ({gemini.model})…")
        checks.append(_attempt("Gemini", "Text", text))
        on_step(f"Gemini embeddings ({gemini.embedding_model})…")
        checks.append(_attempt("Gemini", "Embeddings", embedding))
        if settings.gemini_grounding:
            on_step(f"Gemini grounding ({gemini.grounding_model})…")
            checks.append(_attempt("Gemini", "Grounding", grounding))
        else:
            checks.append(Check("Gemini", "Grounding", "off", "GEMINI_GROUNDING=false"))

    client = autocomplete or AutocompleteClient.from_settings(settings)
    client.cache = None

    def suggest() -> str:
        return f"{len(client.suggest('swimming pool'))} suggestions for “swimming pool”"

    on_step("Google autocomplete…")
    checks.append(_attempt("Google", "Autocomplete", suggest))
    return checks
