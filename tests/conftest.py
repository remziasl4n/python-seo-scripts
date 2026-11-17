import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from seo_toolkit.core import db
from seo_toolkit.core.config import Settings, reload_settings
from seo_toolkit.core.sites import import_site_files

REPO = Path(__file__).resolve().parents[1]
ENV_PREFIXES = (
    "SEO_",
    "GEMINI_",
    "GOOGLE_",
    "CRAWLER_",
    "DATAFORSEO_",
    "SERPAPI_",
    "AHREFS_",
    "SEMRUSH_",
    "DATABASE_",
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway Postgres database for this test session, with the real migrations applied.

    Never touches your own seo_toolkit database.
    """
    url = f"postgresql+psycopg:///seo_toolkit_test_{os.getpid()}"
    try:
        db.create_database_if_missing(url)
    except db.DatabaseError as e:
        pytest.exit(f"The tests need Postgres.\n{e}", returncode=1)
    db.migrate(url)
    yield url
    db.get_engine(url).dispose()
    maintenance = create_engine("postgresql+psycopg:///postgres", isolation_level="AUTOCOMMIT")
    with maintenance.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.rsplit("/", 1)[-1]}" WITH (FORCE)'))
    maintenance.dispose()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[Path]:
    """An empty project folder, set as the current directory, with a fresh test database.

    Clears any real settings from the environment so tests never see your keys, points
    DATABASE_URL at the test database, empties it, and imports the example site, the
    same way `seo db setup` does for a new install.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sites = tmp_path / "config" / "sites"
    sites.mkdir(parents=True)
    shutil.copy(REPO / "config" / "sites" / "example.yaml", sites / "example.yaml")

    for var in list(os.environ):
        if var.startswith(ENV_PREFIXES):
            monkeypatch.delenv(var)
    monkeypatch.setenv("DATABASE_URL", database_url)
    with db.get_engine(database_url).begin() as connection:
        connection.execute(text("TRUNCATE runs, sites"))
        connection.execute(text("DELETE FROM workspaces WHERE id <> 'local'"))
    import_site_files(Settings(_env_file=None, project_dir=tmp_path))  # type: ignore[call-arg]
    monkeypatch.chdir(tmp_path)
    reload_settings()
    yield tmp_path
    reload_settings()


@pytest.fixture
def settings(project: Path) -> Settings:
    return Settings(_env_file=None, project_dir=project)  # type: ignore[call-arg]
