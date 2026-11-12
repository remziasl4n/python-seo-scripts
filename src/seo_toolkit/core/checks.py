"""Setup checks, shared by `seo doctor` and the dashboard's Setup page.

`config_checks` only reads files. `live_checks` makes one small real call to each
configured API (one Gemini text call, one embedding, one grounded search, one
autocomplete request), bypassing the cache.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from seo_toolkit.core.config import ConfigError, Settings, load_site
from seo_toolkit.core.errors import ToolkitError

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

    try:
        site = load_site(site_name, settings)
    except ConfigError as e:
        checks.append(Check("Site", "Site file", "fail", str(e)))
    else:
        checks.append(Check("Site", "Site file", "ok", f"{site.name}: {site.domain}"))
        if site.name == "example":
            checks.append(
                Check(
                    "Site",
                    "Your own site",
                    "warn",
                    "Using the example site. Copy config/sites/example.yaml to "
                    "config/sites/<your-site>.yaml and set SEO_SITE in .env.",
                )
            )
        empty = [f for f in ("source_context", "central_entity") if not getattr(site, f).strip()]
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


def live_checks(
    settings: Settings, gemini: Any | None = None, autocomplete: Any | None = None
) -> list[Check]:
    """Real calls to each configured API. `gemini` / `autocomplete` let tests pass fakes."""
    from seo_toolkit.connectors.autocomplete import AutocompleteClient
    from seo_toolkit.connectors.gemini import Gemini

    checks = []
    if gemini is None and settings.gemini_api_key is None:
        checks.append(Check("Gemini", "Connection", "off", "Add GEMINI_API_KEY to test Gemini."))
    else:
        gemini = gemini or Gemini.from_settings(settings)
        gemini.cache = None  # a live check must reach the API

        def text() -> str:
            reply = gemini.generate("Reply with the single word OK.")
            return f"{gemini.model} replied “{reply.strip()[:40]}”"

        def embedding() -> str:
            vectors = gemini.embed(["swimming pool"])
            return f"{gemini.embedding_model}: {vectors.shape[1]} dimensions"

        def grounding() -> str:
            answer = gemini.ground("What is the date today?")
            return (
                f"Ran {len(answer.search_queries)} Google search(es), {len(answer.sources)} sources"
            )

        checks.append(_attempt("Gemini", "Text", text))
        checks.append(_attempt("Gemini", "Embeddings", embedding))
        if settings.gemini_grounding:
            checks.append(_attempt("Gemini", "Grounding", grounding))
        else:
            checks.append(Check("Gemini", "Grounding", "off", "GEMINI_GROUNDING=false"))

    client = autocomplete or AutocompleteClient.from_settings(settings)
    client.cache = None

    def suggest() -> str:
        return f"{len(client.suggest('swimming pool'))} suggestions for “swimming pool”"

    checks.append(_attempt("Google", "Autocomplete", suggest))
    return checks
