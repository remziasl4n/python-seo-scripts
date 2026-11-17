"""Settings from .env, and the shape of a site's settings.

.env holds secrets and machine settings (see .env.example). Everything about a
website is a SiteConfig, stored in the database (core/sites.py) and edited on the
web app's Sites page. YAML files in config/sites/ can be imported and exported.

    settings = get_settings()
    key = settings.require("gemini_api_key")
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from seo_toolkit.core.errors import ToolkitError


class ConfigError(ToolkitError):
    """A setting or site file is missing or invalid. The message says how to fix it."""


def project_root(start: Path | None = None) -> Path:
    """The repo root: the nearest folder at or above `start` that holds pyproject.toml.

    Lets tools and notebooks run from any subfolder and still find .env, config/ and data/.
    """
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").is_file():
            return folder
    return here


def _format_errors(error: ValidationError, env_names: bool = False) -> str:
    lines = []
    for e in error.errors():
        field = ".".join(str(part) for part in e["loc"])
        lines.append(f"  - {field.upper() if env_names else field}: {e['msg']}")
    return "\n".join(lines)


# --- .env settings -----------------------------------------------------------------


class Settings(BaseSettings):
    """Values from environment variables and .env. Field names match the variable names."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `GEMINI_API_KEY=` in .env means "not set"
        extra="ignore",
    )

    project_dir: Path = Field(default_factory=project_root)

    seo_site: str = "example"
    seo_log_level: str = "INFO"
    seo_data_dir: Path = Path("data")
    seo_cache_dir: Path = Path(".cache")
    seo_cache_ttl_hours: float = Field(24, ge=0)

    # Local Postgres over its socket, as your own user: no password needed
    database_url: str = "postgresql+psycopg:///seo_toolkit"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_grounding_model: str | None = None  # None = same as gemini_model
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimensions: int = 768
    gemini_grounding: bool = True
    gemini_timeout_seconds: float = Field(60, gt=0)

    google_application_credentials: Path | None = None
    google_api_key: SecretStr | None = None

    dataforseo_login: str | None = None
    dataforseo_password: SecretStr | None = None
    serpapi_api_key: SecretStr | None = None
    ahrefs_api_key: SecretStr | None = None
    semrush_api_key: SecretStr | None = None

    crawler_user_agent: str = "Mozilla/5.0 (compatible; seo-toolkit/0.1)"
    crawler_concurrency: int = Field(5, ge=1)
    crawler_timeout_seconds: float = Field(20, gt=0)
    crawler_delay_seconds: float = Field(0.5, ge=0)

    # An int field plus this check, rather than Literal[768, ...]: .env values arrive as
    # text, and a Literal of ints won't accept "768"
    @field_validator("gemini_embedding_dimensions")
    @classmethod
    def _supported_dimensions(cls, value: int) -> int:
        if value not in (768, 1536, 3072):
            raise ValueError("must be 768, 1536 or 3072")
        return value

    def resolve(self, path: Path) -> Path:
        """Make a relative path from .env relative to the project root."""
        return path if path.is_absolute() else self.project_dir / path

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.seo_data_dir)

    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def cache_dir(self) -> Path:
        return self.resolve(self.seo_cache_dir)

    @property
    def sites_dir(self) -> Path:
        return self.project_dir / "config" / "sites"

    def require(self, name: str) -> str:
        """Return a setting as plain text, or raise a ConfigError naming the .env variable."""
        value = getattr(self, name)
        if value is None:
            raise ConfigError(
                f"{name.upper()} is not set. Add it to .env "
                "(run `cp .env.example .env` first if you haven't)."
            )
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        if isinstance(value, Path):
            return str(self.resolve(value))
        return str(value)


def get_settings() -> Settings:
    """Settings from the environment and the project's .env.

    Read once, then again whenever .env is saved, so a running dashboard picks up
    new keys and models without a restart.
    """
    root = project_root()
    try:
        saved_at: int | None = (root / ".env").stat().st_mtime_ns
    except OSError:
        saved_at = None
    return _load_settings(root, saved_at)


@lru_cache(maxsize=4)
def _load_settings(root: Path, saved_at: int | None) -> Settings:
    try:
        return Settings(_env_file=root / ".env", project_dir=root)  # type: ignore[call-arg]
    except ValidationError as e:
        raise ConfigError(f"Invalid value in .env:\n{_format_errors(e, env_names=True)}") from e


def reload_settings() -> None:
    """Forget loaded settings, e.g. after changing environment variables in a test."""
    _load_settings.cache_clear()


# --- Sites -------------------------------------------------------------------------
# Sites live in the database (see core/sites.py). YAML files are for import and export.


class Section(BaseModel):
    """A part of the site and its role in the topical map."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(title="Path", description="URL path prefix, e.g. /blog/")
    name: str = Field(title="Name", min_length=1)
    role: Literal["core", "outer"] = Field(
        title="Role",
        description="core: the central entity's main attribute; outer: supporting topics",
    )

    @field_validator("path")
    @classmethod
    def _path_starts_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("must start with '/', e.g. /blog/")
        return value


class SiteConfig(BaseModel):
    """One website's settings: who it's for, what it's about, and where its data is."""

    model_config = ConfigDict(extra="forbid")  # a typo in a YAML file is an error, not ignored

    name: str = Field(
        title="Name",
        description="Short id used in links and run history, e.g. acme-pools",
        pattern=r"^[a-z0-9][a-z0-9-]{0,62}$",
    )
    domain: str = Field(title="Domain", description="Full URL, e.g. https://www.example.com/")
    country: str = Field("us", title="Country", description="Two-letter code, e.g. us")
    language: str = Field("en", title="Language", description="Two-letter code, e.g. en")

    source_context: str = Field(
        "",
        title="Source context",
        description="Why the site exists and how it makes money. Decides what to cover.",
    )
    central_entity: str = Field(
        "", title="Central entity", description="The thing every section is about"
    )
    entity_type: str = Field("", title="Entity type", description="e.g. product, service, place")
    sections: list[Section] = Field([], title="Sections")

    brand_terms: list[str] = Field(
        [], title="Brand terms", description="Words that mark a query as branded"
    )
    competitors: list[str] = Field([], title="Competitors", description="Competitor URLs")

    gsc_property: str = Field(
        "",
        title="Search Console property",
        description="sc-domain:example.com, or the full URL prefix",
    )
    ga4_property_id: str = Field("", title="GA4 property ID", description="Numeric, optional")
    sitemaps: list[str] = Field([], title="Sitemaps", description="Sitemap URLs")

    @field_validator("brand_terms", "competitors", "sitemaps")
    @classmethod
    def _drop_blank_lines(cls, values: list[str]) -> list[str]:
        return [v.strip() for v in values if v.strip()]

    @field_validator("domain")
    @classmethod
    def _domain_is_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must be a full URL, e.g. https://www.example.com/")
        return value

    @field_validator("country", "language")
    @classmethod
    def _two_letter_code(cls, value: str) -> str:
        if len(value) != 2 or not value.isalpha():
            raise ValueError("must be a two-letter code, e.g. us / en")
        return value.lower()

    @field_validator("ga4_property_id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        # An unquoted 123456789 in YAML arrives as an int
        return str(value) if isinstance(value, int) else value

    def is_brand(self, query: str) -> bool:
        """True if the query contains any of the site's brand terms."""
        query = query.lower()
        return any(term.lower() in query for term in self.brand_terms)

    def section_for(self, url: str) -> Section | None:
        """The most specific section whose path the URL falls under, if any."""
        path = urlsplit(url).path or "/"
        matches = [s for s in self.sections if path.startswith(s.path)]
        return max(matches, key=lambda s: len(s.path), default=None)


def load_site_file(path: Path) -> SiteConfig:
    """Read and check one site YAML file (for import into the database)."""
    if not path.is_file():
        raise ConfigError(f"No site file at {path}.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML:\n{e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} should contain settings like `name: ...`, one per line.")

    try:
        return SiteConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} has invalid settings:\n{_format_errors(e)}") from e
