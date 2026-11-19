"""Postgres: tables, sessions and setup.

    with session(settings) as s:
        s.add(Run(...))

Every table that holds user data has a `workspace_id`. Running locally it's always
"local"; a hosted version would take it from the signed-in user's organisation.
Table changes go through Alembic migrations in src/seo_toolkit/migrations/ (see
docs/architecture.md). `setup_database()` creates the database and applies them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from seo_toolkit.core.config import Settings
from seo_toolkit.core.errors import ToolkitError

LOCAL_WORKSPACE = "local"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class DatabaseError(ToolkitError):
    """The database can't be reached or isn't set up. The message says what to run."""


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """One tool run: what was asked, how it went, and where its results are."""

    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[str] = mapped_column(String(100), index=True)
    tool_title: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(100))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    refresh: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    row_count: Mapped[int | None]
    output: Mapped[str | None] = mapped_column(Text)  # results file, relative to the project
    report: Mapped[str | None] = mapped_column(Text)  # Markdown write-up, relative to the project


class Site(Base):
    """A website tools run against. Columns mirror SiteConfig (core/config.py)."""

    __tablename__ = "sites"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2))
    language: Mapped[str] = mapped_column(String(2))
    source_context: Mapped[str] = mapped_column(Text)
    central_entity: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    brand_terms: Mapped[list[str]] = mapped_column(JSONB)
    competitors: Mapped[list[str]] = mapped_column(JSONB)
    gsc_property: Mapped[str] = mapped_column(Text)
    ga4_property_id: Mapped[str] = mapped_column(Text)
    sitemaps: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    """A draft in the content editor: the page being written, and the brief it's scored on."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    site: Mapped[str] = mapped_column(String(100))
    keyword: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    brief_run_id: Mapped[str | None] = mapped_column(String(32))  # the content editor run
    title: Mapped[str] = mapped_column(Text, default="")
    meta_description: Mapped[str] = mapped_column(Text, default="")
    url_slug: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")  # HTML
    answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)  # last answer check
    answers_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None]
    word_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Connections ---------------------------------------------------------------------


@lru_cache(maxsize=8)
def get_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


@lru_cache(maxsize=8)
def _sessions(url: str) -> sessionmaker[Session]:
    return sessionmaker(get_engine(url), expire_on_commit=False)


def _database_name(url: str) -> str:
    return make_url(url).database or ""


def _explain(error: OperationalError, url: str) -> DatabaseError:
    message = str(error.orig or error).lower()
    name = _database_name(url)
    if "does not exist" in message and "database" in message:
        return DatabaseError(f"The database {name!r} doesn't exist yet. Run: uv run seo db setup")
    if (
        "connection refused" in message
        or "no such file" in message
        or "could not connect" in message
    ):
        return DatabaseError(
            "Can't reach Postgres. Start it with: brew services start postgresql@17\n"
            "(not installed? brew install postgresql@17 pgvector)"
        )
    return DatabaseError(f"Database error: {error.orig or error}")


@contextmanager
def session(settings: Settings) -> Iterator[Session]:
    """A session that commits when the block ends, or rolls back on an error."""
    try:
        with _sessions(settings.database_url).begin() as s:
            yield s
    except OperationalError as e:
        raise _explain(e, settings.database_url) from e


# --- Setup ---------------------------------------------------------------------------


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def create_database_if_missing(url: str) -> bool:
    """Create the database named in `url`. Returns True if it had to be created."""
    name = _database_name(url)
    maintenance = make_url(url).set(database="postgres")
    engine = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            return not exists
    except OperationalError as e:
        raise _explain(e, url) from e
    finally:
        engine.dispose()


def migrate(url: str) -> None:
    """Apply any migrations the database doesn't have yet."""
    try:
        command.upgrade(alembic_config(url), "head")
    except OperationalError as e:
        raise _explain(e, url) from e


def setup_database(settings: Settings) -> bool:
    """Create the database if needed and bring its tables up to date."""
    created = create_database_if_missing(settings.database_url)
    migrate(settings.database_url)
    return created


def is_ready(settings: Settings) -> tuple[bool, str]:
    """(ready, explanation) for the setup checks: reachable, and tables up to date."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config(settings.database_url)).get_current_head()
    try:
        with get_engine(settings.database_url).connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            has_runs = inspect(connection).has_table("runs")
    except OperationalError as e:
        return False, str(_explain(e, settings.database_url))
    if current != head or not has_runs:
        return False, "Tables are missing or out of date. Run: uv run seo db setup"
    return True, f"{_database_name(settings.database_url)} (migration {head})"
