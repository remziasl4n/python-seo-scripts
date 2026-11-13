"""Dashboard tests, using Streamlit's headless test runner (no browser needed)."""

import pytest
from streamlit.testing.v1 import AppTest

from fakes import FakeAutocomplete
from seo_toolkit.connectors.autocomplete import AutocompleteClient

MAIN = "src/seo_toolkit/app/main.py"
TOOL_PAGE = """
from seo_toolkit.app import views
from seo_toolkit.tools.research.autocomplete import Autocomplete
views.tool_page(Autocomplete)()
"""


@pytest.fixture
def repo_main(project):
    from conftest import REPO

    return str(REPO / MAIN)


@pytest.fixture
def fake_autocomplete(monkeypatch) -> FakeAutocomplete:
    fake = FakeAutocomplete()
    monkeypatch.setattr(AutocompleteClient, "from_settings", classmethod(lambda cls, *a, **k: fake))
    return fake


def test_home_renders(repo_main):
    at = AppTest.from_file(repo_main, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "SEO Toolkit"
    assert at.sidebar.selectbox(key="site").value == "example"
    assert any("Setup" in w.value for w in at.warning)


def test_setup_page_renders(project):
    at = AppTest.from_string(
        "from seo_toolkit.app import views\nviews.setup()", default_timeout=30
    ).run()
    assert not at.exception
    assert at.button[0].label == "Test connections"


def test_results_page_empty_then_lists_files(project, settings):
    script = "from seo_toolkit.app import views\nviews.results()"
    at = AppTest.from_string(script, default_timeout=30).run()
    assert "No results yet" in at.info[0].value

    folder = settings.outputs_dir / "autocomplete"
    folder.mkdir(parents=True)
    (folder / "2026-11-12_100000_pool.csv").write_text("suggestion\npool cost\n")
    at = AppTest.from_string(script, default_timeout=30).run()
    assert not at.exception
    assert at.dataframe[0].value["suggestion"].tolist() == ["pool cost"]


def test_tool_page_runs_tool_and_shows_results(project, fake_autocomplete, settings):
    at = AppTest.from_string(TOOL_PAGE, default_timeout=30).run()
    assert at.title[0].value == "Autocomplete"
    at.text_area(key="research/autocomplete.seeds").input("pool cost")
    at.selectbox(key="research/autocomplete.expand").select("seed only")
    at.button[0].click().run()

    assert not at.exception
    assert not at.error
    assert [m.label for m in at.metric][:2] == ["Suggestions", "Seeds"]
    assert at.dataframe[0].value["suggestion"].iloc[0] in {
        "pool cost texas",
        "pool cost calculator",
    }
    assert fake_autocomplete.calls == [("pool cost", "us", "en")]
    assert list((settings.outputs_dir / "autocomplete").glob("*_pool-cost.csv"))


def test_tool_page_shows_validation_errors(project, fake_autocomplete):
    at = AppTest.from_string(TOOL_PAGE, default_timeout=30).run()
    at.button[0].click().run()  # no seeds entered
    assert "Seed queries" in at.error[0].value
    assert fake_autocomplete.calls == []
