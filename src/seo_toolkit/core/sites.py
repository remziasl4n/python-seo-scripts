"""Sites: the websites tools run against, stored in Postgres per workspace.

    site = load_site("acme-pools")            # a SiteConfig
    create_site(settings, site)               # or update_site / delete_site
    import_site_files(settings)               # config/sites/*.yaml -> database (once each)
    site_to_yaml(site)                        # for export and backups

With no name, load_site uses SEO_SITE from .env if that site exists, otherwise the
first site alphabetically.
"""

from __future__ import annotations

import logging

import yaml
from sqlalchemy import select

from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, get_settings, load_site_file
from seo_toolkit.core.db import LOCAL_WORKSPACE, Site, session
from seo_toolkit.core.errors import ToolkitError

log = logging.getLogger(__name__)

HOW_TO_ADD = "Add one on the Sites page of the web app."


class SiteNotFound(ConfigError):
    """No site by that name in this workspace."""


class SiteExists(ToolkitError):
    """A site by that name already exists in this workspace."""


def _to_config(row: Site) -> SiteConfig:
    return SiteConfig.model_validate(
        {field: getattr(row, field) for field in SiteConfig.model_fields}
    )


def _values(site: SiteConfig) -> dict[str, object]:
    return site.model_dump(mode="json")


def list_sites(settings: Settings, workspace_id: str = LOCAL_WORKSPACE) -> list[SiteConfig]:
    with session(settings) as s:
        rows = s.scalars(select(Site).where(Site.workspace_id == workspace_id).order_by(Site.name))
        return [_to_config(row) for row in rows]


def default_site_name(settings: Settings, workspace_id: str = LOCAL_WORKSPACE) -> str:
    names = [site.name for site in list_sites(settings, workspace_id)]
    if not names:
        raise SiteNotFound(f"There are no sites yet. {HOW_TO_ADD}")
    return settings.seo_site if settings.seo_site in names else names[0]


def load_site(
    name: str | None = None,
    settings: Settings | None = None,
    workspace_id: str = LOCAL_WORKSPACE,
) -> SiteConfig:
    settings = settings or get_settings()
    name = name or default_site_name(settings, workspace_id)
    with session(settings) as s:
        row = s.get(Site, (workspace_id, name))
        if row is not None:
            return _to_config(row)
    names = [site.name for site in list_sites(settings, workspace_id)]
    raise SiteNotFound(
        f"There's no site called {name!r}. Sites: {', '.join(names) or 'none yet'}. {HOW_TO_ADD}"
    )


def create_site(
    settings: Settings, site: SiteConfig, workspace_id: str = LOCAL_WORKSPACE
) -> SiteConfig:
    with session(settings) as s:
        if s.get(Site, (workspace_id, site.name)) is not None:
            raise SiteExists(f"A site called {site.name!r} already exists. Pick another name.")
        s.add(Site(workspace_id=workspace_id, **_values(site)))
    return site


def update_site(
    settings: Settings, name: str, site: SiteConfig, workspace_id: str = LOCAL_WORKSPACE
) -> SiteConfig:
    """Replace a site's settings. Names can't change: run history refers to them."""
    if site.name != name:
        raise ConfigError("A site's name can't be changed. Create a new site instead.")
    with session(settings) as s:
        row = s.get(Site, (workspace_id, name))
        if row is None:
            raise SiteNotFound(f"There's no site called {name!r}.")
        for field, value in _values(site).items():
            setattr(row, field, value)
    return site


def delete_site(settings: Settings, name: str, workspace_id: str = LOCAL_WORKSPACE) -> None:
    """Delete a site. Its past runs stay in the history."""
    with session(settings) as s:
        row = s.get(Site, (workspace_id, name))
        if row is None:
            raise SiteNotFound(f"There's no site called {name!r}.")
        s.delete(row)


def import_site_files(
    settings: Settings, workspace_id: str = LOCAL_WORKSPACE
) -> tuple[list[str], list[str]]:
    """Add config/sites/*.yaml to the database, skipping sites that already exist.

    Returns (imported names, problems). Safe to repeat.
    """
    imported: list[str] = []
    problems: list[str] = []
    if not settings.sites_dir.is_dir():
        return imported, problems
    existing = {site.name for site in list_sites(settings, workspace_id)}
    for path in sorted(settings.sites_dir.glob("*.yaml")):
        try:
            site = load_site_file(path)
        except ConfigError as e:
            problems.append(str(e))
            continue
        if site.name in existing:
            continue
        create_site(settings, site, workspace_id)
        existing.add(site.name)
        imported.append(site.name)
    return imported, problems


def site_to_yaml(site: SiteConfig) -> str:
    """The site as a YAML file that import_site_files can read back."""
    return yaml.safe_dump(site.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
