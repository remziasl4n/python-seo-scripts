import numpy as np

from fakes import FakeAutocomplete
from seo_toolkit.connectors.autocomplete import AutocompleteError
from seo_toolkit.connectors.gemini import GeminiError, GroundedAnswer, Source
from seo_toolkit.core.checks import config_checks, live_checks
from seo_toolkit.core.config import Settings


def by_name(checks):
    return {c.name: c for c in checks}


def test_fresh_project_warns_but_does_not_fail(settings):
    checks = by_name(config_checks(settings))
    assert checks[".env file"].status == "warn"
    assert checks["Site file"].status == "ok"
    assert checks["Your own site"].status == "warn"
    assert checks["GEMINI_API_KEY"].status == "off"
    assert not any(c.status == "fail" for c in checks.values())


def test_missing_site_fails(settings):
    assert by_name(config_checks(settings, "nope"))["Site file"].status == "fail"


def test_empty_semantic_context_warns(settings):
    (settings.sites_dir / "bare.yaml").write_text("name: bare\ndomain: https://bare.com/\n")
    check = by_name(config_checks(settings, "bare"))["Semantic context"]
    assert check.status == "warn"
    assert "source_context" in check.detail


def test_credentials_path_must_exist(project):
    settings = Settings(
        _env_file=None, project_dir=project, google_application_credentials="credentials/x.json"
    )
    assert by_name(config_checks(settings))["GOOGLE_APPLICATION_CREDENTIALS"].status == "fail"
    (project / "credentials").mkdir()
    (project / "credentials" / "x.json").write_text("{}")
    assert by_name(config_checks(settings))["GOOGLE_APPLICATION_CREDENTIALS"].status == "ok"


class FakeGemini:
    model = "gemini-test"
    grounding_model = "gemini-grounding-test"
    embedding_model = "gemini-embedding-test"

    def __init__(self, fail_embeddings: bool = False) -> None:
        self.cache = object()
        self.fail_embeddings = fail_embeddings
        self.searches: tuple[str, ...] = ("top news today",)

    def generate(self, prompt):
        return "OK"

    def embed(self, texts):
        if self.fail_embeddings:
            raise GeminiError("model not found")
        return np.ones((1, 768))

    def ground(self, prompt):
        return GroundedAnswer(
            "Headlines", self.searches, (Source("a", "u", "a.com"),), (), self.grounding_model
        )


def test_live_checks_report_each_api(settings):
    gemini = FakeGemini()
    checks = by_name(live_checks(settings, gemini=gemini, autocomplete=FakeAutocomplete()))
    assert checks["Text"].status == "ok" and "OK" in checks["Text"].detail
    assert "768 dimensions" in checks["Embeddings"].detail
    assert "1 Google search" in checks["Grounding"].detail
    assert checks["Autocomplete"].status == "ok"
    assert gemini.cache is None  # live checks never answer from the cache


def test_live_checks_report_each_step(settings):
    steps: list[str] = []
    live_checks(
        settings, gemini=FakeGemini(), autocomplete=FakeAutocomplete(), on_step=steps.append
    )
    assert steps == [
        "Gemini text (gemini-test)…",
        "Gemini embeddings (gemini-embedding-test)…",
        "Gemini grounding (gemini-grounding-test)…",
        "Google autocomplete…",
    ]


def test_grounding_without_a_search_fails(settings):
    gemini = FakeGemini()
    gemini.searches = ()
    checks = by_name(live_checks(settings, gemini=gemini, autocomplete=FakeAutocomplete()))
    assert checks["Grounding"].status == "fail"
    assert "without searching" in checks["Grounding"].detail


def test_live_checks_show_failures_without_stopping(settings):
    checks = by_name(
        live_checks(
            settings,
            gemini=FakeGemini(fail_embeddings=True),
            autocomplete=FakeAutocomplete(fail=AutocompleteError("blocked")),
        )
    )
    assert checks["Text"].status == "ok"
    assert checks["Embeddings"].status == "fail"
    assert checks["Grounding"].status == "ok"
    assert checks["Autocomplete"].detail == "blocked"


def test_live_checks_without_key_skip_gemini(settings):
    checks = by_name(live_checks(settings, autocomplete=FakeAutocomplete()))
    assert checks["Connection"].status == "off"
    assert "Text" not in checks


def test_database_check(settings, project):
    assert by_name(config_checks(settings))["Database"].status == "ok"
    missing = Settings(
        _env_file=None, project_dir=project, database_url="postgresql+psycopg:///no_such_db_xyz"
    )
    check = by_name(config_checks(missing))["Database"]
    assert check.status == "fail" and "seo db setup" in check.detail
