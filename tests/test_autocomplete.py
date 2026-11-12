import json

import httpx
import pytest
from pydantic import ValidationError

from fakes import FakeAutocomplete
from seo_toolkit.connectors.autocomplete import URL, AutocompleteClient, AutocompleteError
from seo_toolkit.core.cache import Cache
from seo_toolkit.core.config import load_site
from seo_toolkit.tools.base import RunContext
from seo_toolkit.tools.research.autocomplete import Autocomplete, AutocompleteInputs, variations

# --- Connector ---------------------------------------------------------------------------


def client_with(handler, tmp_path=None, **kwargs) -> AutocompleteClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    cache = Cache(tmp_path / ".cache") if tmp_path else None
    return AutocompleteClient(http, cache=cache, **kwargs)


def ok(request: httpx.Request) -> httpx.Response:
    q = request.url.params["q"]
    return httpx.Response(200, text=json.dumps([q, [f"{q} cost", f"{q} size", 3]]))


def test_suggest_sends_params_and_parses(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return ok(request)

    client = client_with(handler)
    assert client.suggest("pool", country="gb", language="en") == ["pool cost", "pool size"]
    params = seen[0].url.params
    assert str(seen[0].url).startswith(URL)
    assert (params["client"], params["q"], params["gl"], params["hl"]) == (
        "firefox",
        "pool",
        "gb",
        "en",
    )
    assert client.requests == 1


def test_suggest_is_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return ok(request)

    client = client_with(handler, tmp_path)
    client.suggest("pool")
    assert client.suggest("pool") == ["pool cost", "pool size"]
    assert len(calls) == 1
    assert (client.requests, client.cached) == (1, 1)


def test_requests_are_spaced_out():
    sleeps: list[float] = []
    now = [0.0]
    client = client_with(ok, delay_seconds=0.5, sleep=sleeps.append, clock=lambda: now[0])
    client.suggest("a")
    now[0] = 0.2
    client.suggest("b")
    assert sleeps == [pytest.approx(0.3)]


@pytest.mark.parametrize("status", [429, 503])
def test_rate_limit_explains_what_to_do(status):
    client = client_with(lambda request: httpx.Response(status))
    with pytest.raises(AutocompleteError, match="CRAWLER_DELAY_SECONDS"):
        client.suggest("pool")


@pytest.mark.parametrize("body", ["<html>", json.dumps({"unexpected": True})])
def test_bad_response_raises(body):
    client = client_with(lambda request: httpx.Response(200, text=body))
    with pytest.raises(AutocompleteError):
        client.suggest("pool")


def test_network_error_raises():
    def handler(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(AutocompleteError, match="Couldn't reach"):
        client_with(handler).suggest("pool")


# --- Tool --------------------------------------------------------------------------------


@pytest.fixture
def fake() -> FakeAutocomplete:
    return FakeAutocomplete()


@pytest.fixture
def ctx(settings, fake) -> RunContext:
    return RunContext(settings, load_site("example", settings), connectors={"autocomplete": fake})


def test_variations_counts():
    assert len(variations("pool", "seed only", english=True)) == 1
    assert len(variations("pool", "alphabet", english=True)) == 27
    assert len(variations("pool", "questions", english=True)) == 1 + 11 + 7
    assert len(variations("pool", "everything", english=True)) == 45
    assert len(variations("pool", "everything", english=False)) == 27


def test_seeds_are_cleaned():
    inputs = AutocompleteInputs(seeds=["  Pool Cost ", "pool cost", "", "pool size"])
    assert inputs.seeds == ["pool cost", "pool size"]
    with pytest.raises(ValidationError):
        AutocompleteInputs(seeds=["  "])


def test_run_merges_and_ranks(ctx, fake):
    result = Autocomplete().run(AutocompleteInputs(seeds=["pool cost"]), ctx)
    table = result.table
    assert len(fake.calls) == 45
    top = table.iloc[0]
    assert top["suggestion"] == "pool cost calculator"
    assert top["times_seen"] == 45
    assert top["found_via"] == "pool cost"  # first found from the seed itself
    assert top["variation_type"] == "seed"
    assert table["suggestion"].is_unique
    assert result.metrics["Requests to Google"] == 45


def test_brand_suggestions_flagged(ctx):
    table = (
        Autocomplete().run(AutocompleteInputs(seeds=["pool cost"], expand="seed only"), ctx).table
    )
    flags = dict(zip(table["suggestion"], table["is_brand"], strict=True))
    assert flags["acme pools pool cost"] is True
    assert flags["pool cost texas"] is False


def test_site_defaults_and_overrides(ctx, fake):
    Autocomplete().run(AutocompleteInputs(seeds=["pool"], expand="seed only"), ctx)
    Autocomplete().run(
        AutocompleteInputs(seeds=["piscine"], expand="seed only", country="FR", language="fr"), ctx
    )
    assert fake.calls == [("pool", "us", "en"), ("piscine", "fr", "fr")]


def test_non_english_skips_questions_with_a_note(ctx, fake):
    result = Autocomplete().run(AutocompleteInputs(seeds=["piscine"], language="fr"), ctx)
    assert len(fake.calls) == 27
    assert "only exist in English" in result.notes[0]


def test_progress_reported(ctx):
    updates = []
    ctx.progress = lambda fraction, message: updates.append(fraction)
    Autocomplete().run(AutocompleteInputs(seeds=["pool"], expand="alphabet"), ctx)
    assert updates[0] == 0 and updates[-1] == 1.0
    assert updates == sorted(updates)


def test_empty_results_keep_columns(ctx, fake):
    fake.suggest = lambda *args: []  # type: ignore[method-assign]
    table = Autocomplete().run(AutocompleteInputs(seeds=["zzzz"], expand="seed only"), ctx).table
    assert table.empty
    assert "times_seen" in table.columns
