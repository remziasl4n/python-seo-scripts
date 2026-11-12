import os
import shutil
from pathlib import Path

import pytest

from seo_toolkit.core.config import Settings, get_settings

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
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project folder with the example site file, set as the current directory.

    Clears any real settings from the environment so tests never see your keys.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sites = tmp_path / "config" / "sites"
    sites.mkdir(parents=True)
    shutil.copy(REPO / "config" / "sites" / "example.yaml", sites / "example.yaml")

    for var in list(os.environ):
        if var.startswith(ENV_PREFIXES):
            monkeypatch.delenv(var)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def settings(project: Path) -> Settings:
    return Settings(_env_file=None, project_dir=project)  # type: ignore[call-arg]
