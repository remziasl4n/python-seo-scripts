import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, get_settings, load_site_file

REPO = Path(__file__).resolve().parents[1]


def write_site(settings: Settings, name: str, text: str) -> Path:
    path = settings.sites_dir / f"{name}.yaml"
    path.write_text(text)
    return path


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


def test_saving_env_is_picked_up_without_restart(project):
    """A running server must see a key added to .env after it started."""
    env = project / ".env"
    env.write_text("GEMINI_API_KEY=\n")
    assert get_settings().gemini_api_key is None
    assert get_settings() is get_settings()  # unchanged file: not re-read

    env.write_text("GEMINI_API_KEY=new-key\nGEMINI_MODEL=gemini-2.5-flash\n")
    stat = env.stat()
    os.utime(env, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))  # a later save
    settings = get_settings()
    assert settings.require("gemini_api_key") == "new-key"
    assert settings.gemini_model == "gemini-2.5-flash"


def test_env_example_loads_as_copied(project):
    """`cp .env.example .env` must give working settings: every value arrives as text."""
    (project / ".env").write_text((REPO / ".env.example").read_text())
    settings = get_settings()
    assert settings.gemini_embedding_dimensions == 768
    assert settings.gemini_grounding is True
    assert settings.crawler_delay_seconds == 0.5
    assert settings.gemini_api_key is None  # empty in the example


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


# --- Site settings and site files ----------------------------------------------------


def test_repo_example_site_file_is_valid():
    """The committed example is imported into every new database, so it must load."""
    site = load_site_file(REPO / "config" / "sites" / "example.yaml")
    assert site.name == "example"
    assert site.central_entity == "swimming pool"
    assert [s.role for s in site.sections] == ["core", "core", "outer"]


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
        ("name: Has Spaces\ndomain: https://x.com/\n", "name"),
    ],
)
def test_invalid_site_file_names_the_field(settings, yaml_text, field):
    path = write_site(settings, "bad", yaml_text)
    with pytest.raises(ConfigError, match=rf"- {field}:"):
        load_site_file(path)


def test_broken_yaml_is_reported(settings):
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_site_file(write_site(settings, "bad", "name: [unclosed\n"))


def test_numeric_ga4_id_becomes_text(settings):
    path = write_site(
        settings, "num", "name: n\ndomain: https://n.com/\nga4_property_id: 123456789\n"
    )
    assert load_site_file(path).ga4_property_id == "123456789"


def test_blank_list_lines_are_dropped():
    site = SiteConfig(name="x", domain="https://x.com/", brand_terms=[" acme ", "", "  "])
    assert site.brand_terms == ["acme"]


def test_is_brand():
    site = SiteConfig(name="x", domain="https://x.com/", brand_terms=["acme pools", "acmepools"])
    assert site.is_brand("Acme Pools reviews")
    assert site.is_brand("acmepools.com login")
    assert not site.is_brand("pool cost texas")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.example.com/guides/cost/inground/", "/guides/cost/"),  # most specific wins
        ("/guides/opening-a-pool/", "/guides/"),
        ("https://www.example.com/about/", None),
    ],
)
def test_section_for(url, expected):
    site = SiteConfig(
        name="x",
        domain="https://x.com/",
        sections=[
            {"path": "/guides/", "name": "Guides", "role": "outer"},
            {"path": "/guides/cost/", "name": "Cost guides", "role": "core"},
        ],
    )
    section = site.section_for(url)
    assert (section.path if section else None) == expected


def test_site_name_must_be_url_safe():
    with pytest.raises(ValidationError):
        SiteConfig(name="../etc", domain="https://x.com/")
