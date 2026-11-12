import pytest

from seo_toolkit.core.cache import Cache


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, hours: float) -> None:
        self.now += hours * 3600


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(tmp_path, clock) -> Cache:
    return Cache(tmp_path / ".cache", ttl_hours=24, clock=clock)


def test_round_trip(cache):
    cache.set("autocomplete", {"q": "pool cost"}, ["pool cost texas", "pool cost calculator"])
    assert cache.get("autocomplete", {"q": "pool cost"}) == [
        "pool cost texas",
        "pool cost calculator",
    ]


def test_miss_returns_none(cache):
    assert cache.get("autocomplete", {"q": "never stored"}) is None


def test_key_order_does_not_matter(cache):
    cache.set("gsc", {"site": "a", "days": 90}, 1)
    assert cache.get("gsc", {"days": 90, "site": "a"}) == 1


def test_namespaces_are_separate(cache):
    cache.set("gemini.generate", "same key", "text")
    assert cache.get("gemini.embed", "same key") is None


def test_entries_expire(cache, clock):
    cache.set("gsc", "k", 1)
    clock.advance(23.9)
    assert cache.get("gsc", "k") == 1
    clock.advance(0.2)
    assert cache.get("gsc", "k") is None


def test_no_ttl_keeps_forever(tmp_path, clock):
    cache = Cache(tmp_path, ttl_hours=None, clock=clock)
    cache.set("gsc", "k", 1)
    clock.advance(24 * 365)
    assert cache.get("gsc", "k") == 1


def test_refresh_ignores_old_entries_but_saves_new(tmp_path, clock):
    Cache(tmp_path, clock=clock).set("gsc", "k", "old")
    refreshing = Cache(tmp_path, refresh=True, clock=clock)
    assert refreshing.get_or_set("gsc", "k", lambda: "new") == "new"
    assert Cache(tmp_path, clock=clock).get("gsc", "k") == "new"


def test_get_or_set_computes_once(cache):
    calls = []

    def fetch():
        calls.append(1)
        return {"rows": 3}

    assert cache.get_or_set("gsc", "k", fetch) == {"rows": 3}
    assert cache.get_or_set("gsc", "k", fetch) == {"rows": 3}
    assert len(calls) == 1


def test_cached_none_is_still_a_hit(cache):
    calls = []
    cache.get_or_set("kg", "unknown entity", lambda: calls.append(1))
    cache.get_or_set("kg", "unknown entity", lambda: calls.append(1))
    assert len(calls) == 1


def test_corrupt_file_counts_as_miss(cache):
    cache.set("gsc", "k", 1)
    path = next((cache.directory / "gsc").glob("*.json"))
    path.write_text("{not json")
    assert cache.get("gsc", "k") is None
    assert cache.get_or_set("gsc", "k", lambda: 2) == 2


def test_no_temp_files_left_behind(cache):
    cache.set("gsc", "k", 1)
    assert not list(cache.directory.rglob("*.tmp"))


def test_unserialisable_value_raises_and_leaves_nothing(cache):
    with pytest.raises(TypeError):
        cache.set("gsc", "k", {1, 2, 3}.__iter__())
    assert not list(cache.directory.rglob("*.tmp"))


def test_clear(cache):
    cache.set("gsc", "a", 1)
    cache.set("gsc", "b", 2)
    cache.set("kg", "c", 3)
    assert cache.clear("gsc") == 2
    assert cache.get("kg", "c") == 3
    assert cache.clear() == 1
    assert cache.clear() == 0


@pytest.mark.parametrize("namespace", ["Gemini", "../escape", "", "a/b"])
def test_bad_namespace_rejected(cache, namespace):
    with pytest.raises(ValueError):
        cache.set(namespace, "k", 1)


def test_from_settings_uses_cache_dir(settings):
    cache = Cache.from_settings(settings)
    assert cache.directory == settings.project_dir / ".cache"
    assert cache.ttl_hours == 24
