from pathlib import Path

import pytest

from seo_toolkit.core.config import ConfigError, Settings, get_settings, load_site


def write_site(settings: Settings, name: str, text: str) -> None:
    (settings.sites_dir / f"{name}.yaml").write_text(text)


def test_example_site_loads(settings):
    site = load_site("example", settings)
    assert site.central_entity == "swimming pool"
    assert [s.role for s in site.sections] == ["core", "core", "outer"]
    assert site.ga4_property_id == ""


def test_default_site_comes_from_env(settings, monkeypatch):
    monkeypatch.setenv("SEO_SITE", "example")
    assert (
        load_site(settings=Settings(_env_file=None, project_dir=settings.project_dir)).name
        == "example"
    )


def test_dotenv_values_and_empty_means_unset(project):
    (project / ".env").write_text("GEMINI_API_KEY=abc123\nSEO_SITE=mysite\nGOOGLE_API_KEY=\n")
    settings = Settings(_env_file=project / ".env", project_dir=project)
    assert settings.require("gemini_api_key") == "abc123"
    assert settings.seo_site == "mysite"
    assert settings.google_api_key is None


def test_secrets_are_hidden_when_printed(project):
    settings = Settings(_env_file=None, project_dir=project, gemini_api_key="abc123")
    assert "abc123" not in repr(settings)


def test_require_names_the_env_variable(settings):
    with pytest.raises(ConfigError, match="GEMINI_API_KEY is not set"):
        settings.require("gemini_api_key")


def test_invalid_env_value_is_reported(project):
    (project / ".env").write_text("GEMINI_EMBEDDING_DIMENSIONS=1000\n")
    with pytest.raises(ConfigError, match="GEMINI_EMBEDDING_DIMENSIONS"):
        get_settings()


def test_relative_paths_resolve_against_project(settings, tmp_path):
    assert settings.data_dir == settings.project_dir / "data"
    assert settings.outputs_dir == settings.project_dir / "data" / "outputs"
    absolute = Settings(
        _env_file=None, project_dir=settings.project_dir, seo_cache_dir=tmp_path / "c"
    )
    assert absolute.cache_dir == tmp_path / "c"


def test_project_root_found_from_subfolder(project, monkeypatch):
    (project / "notebooks").mkdir()
    monkeypatch.chdir(project / "notebooks")
    assert get_settings().project_dir == project.resolve()


def test_missing_site_lists_available(settings):
    with pytest.raises(ConfigError, match="Available sites: example"):
        load_site("nope", settings)


@pytest.mark.parametrize(
    ("yaml_text", "field"),
    [
        ("name: x\ndomain: www.x.com\n", "domain"),
        ("name: x\ndomain: https://x.com/\ncountry: usa\n", "country"),
        (
            "name: x\ndomain: https://x.com/\nsections:\n  - {path: /b/, name: B, role: pillar}\n",
            "sections.0.role",
        ),
        (
            "name: x\ndomain: https://x.com/\nsections:\n  - {path: blog, name: B, role: core}\n",
            "sections.0.path",
        ),
        ("name: x\ndomain: https://x.com/\ncentral_entitty: pool\n", "central_entitty"),
    ],
)
def test_invalid_site_names_the_field(settings, yaml_text, field):
    write_site(settings, "bad", yaml_text)
    with pytest.raises(ConfigError, match=rf"- {field}:"):
        load_site("bad", settings)


def test_broken_yaml_is_reported(settings):
    write_site(settings, "bad", "name: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_site("bad", settings)


def test_numeric_ga4_id_becomes_text(settings):
    write_site(settings, "num", "name: n\ndomain: https://n.com/\nga4_property_id: 123456789\n")
    assert load_site("num", settings).ga4_property_id == "123456789"


def test_is_brand(settings):
    site = load_site("example", settings)
    assert site.is_brand("Acme Pools reviews")
    assert site.is_brand("acmepools.com login")
    assert not site.is_brand("pool cost texas")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.example.com/pools/fiberglass/", "/pools/"),
        ("/guides/opening-a-pool/", "/guides/"),
        ("https://www.example.com/about/", None),
    ],
)
def test_section_for(settings, url, expected):
    section = load_site("example", settings).section_for(url)
    assert (section.path if section else None) == expected


def test_section_for_prefers_most_specific(settings):
    write_site(
        settings,
        "nested",
        "name: n\ndomain: https://n.com/\nsections:\n"
        "  - {path: /guides/, name: Guides, role: outer}\n"
        "  - {path: /guides/cost/, name: Cost guides, role: core}\n",
    )
    section = load_site("nested", settings).section_for("/guides/cost/inground/")
    assert section is not None and section.role == "core"


def test_repo_example_site_is_valid():
    """The committed example must always load, since users copy it."""
    repo = Path(__file__).resolve().parents[1]
    settings = Settings(_env_file=None, project_dir=repo)
    assert load_site("example", settings).domain.startswith("https://")
