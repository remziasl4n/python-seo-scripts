import pytest

from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, load_site_file
from seo_toolkit.core.db import Workspace, session
from seo_toolkit.core.sites import (
    SiteExists,
    SiteNotFound,
    create_site,
    default_site_name,
    delete_site,
    import_site_files,
    list_sites,
    load_site,
    site_to_yaml,
    update_site,
)


def acme(**changes) -> SiteConfig:
    fields = {"name": "acme", "domain": "https://acme.com/", "central_entity": "anvil"}
    return SiteConfig(**{**fields, **changes})


def test_example_is_imported_for_every_test(settings):
    site = load_site("example", settings)
    assert site.central_entity == "swimming pool"
    assert [s.role for s in site.sections] == ["core", "core", "outer"]


def test_create_list_and_load(settings):
    create_site(settings, acme(sections=[{"path": "/anvils/", "name": "Anvils", "role": "core"}]))
    assert [s.name for s in list_sites(settings)] == ["acme", "example"]
    loaded = load_site("acme", settings)
    assert loaded == acme(sections=[{"path": "/anvils/", "name": "Anvils", "role": "core"}])


def test_names_are_unique(settings):
    create_site(settings, acme())
    with pytest.raises(SiteExists, match="already exists"):
        create_site(settings, acme())


def test_update_replaces_settings_but_not_the_name(settings):
    create_site(settings, acme())
    update_site(settings, "acme", acme(central_entity="hammer", brand_terms=["acme"]))
    assert load_site("acme", settings).central_entity == "hammer"
    with pytest.raises(ConfigError, match="can't be changed"):
        update_site(settings, "acme", SiteConfig(name="acme-2", domain="https://a.com/"))
    with pytest.raises(SiteNotFound):
        update_site(settings, "ghost", SiteConfig(name="ghost", domain="https://g.com/"))


def test_delete(settings):
    create_site(settings, acme())
    delete_site(settings, "acme")
    assert [s.name for s in list_sites(settings)] == ["example"]
    with pytest.raises(SiteNotFound):
        delete_site(settings, "acme")


def test_missing_site_lists_what_exists(settings):
    with pytest.raises(SiteNotFound, match=r"no site called 'nope'\. Sites: example"):
        load_site("nope", settings)


def test_default_site(settings, project):
    create_site(settings, acme())
    assert default_site_name(settings) == "example"  # SEO_SITE defaults to example
    chosen = Settings(_env_file=None, project_dir=project, seo_site="acme")
    assert load_site(settings=chosen).name == "acme"
    gone = Settings(_env_file=None, project_dir=project, seo_site="deleted-site")
    assert default_site_name(gone) == "acme"  # SEO_SITE names a missing site: first by name


def test_no_sites_at_all(settings):
    delete_site(settings, "example")
    with pytest.raises(SiteNotFound, match="no sites yet"):
        load_site(settings=settings)


def test_sites_are_scoped_to_a_workspace(settings):
    with session(settings) as s:
        s.add(Workspace(id="other", name="Other"))
    create_site(settings, acme(), workspace_id="other")
    assert [s.name for s in list_sites(settings, "other")] == ["acme"]
    assert [s.name for s in list_sites(settings)] == ["example"]
    with pytest.raises(SiteNotFound):
        load_site("acme", settings)


def test_import_skips_existing_and_reports_bad_files(settings):
    (settings.sites_dir / "acme.yaml").write_text(site_to_yaml(acme()))
    (settings.sites_dir / "broken.yaml").write_text("name: [oops\n")
    imported, problems = import_site_files(settings)
    assert imported == ["acme"]  # example was already there
    assert len(problems) == 1 and "broken.yaml" in problems[0]
    assert import_site_files(settings) == ([], problems)  # safe to repeat


def test_yaml_export_round_trips(settings, tmp_path):
    original = load_site("example", settings)
    path = tmp_path / "example.yaml"
    path.write_text(site_to_yaml(original))
    assert load_site_file(path) == original
