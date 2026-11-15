"""Alembic environment: which database to migrate, and which tables it should match."""

from alembic import context
from sqlalchemy import create_engine

from seo_toolkit.core.config import get_settings
from seo_toolkit.core.db import Base

config = context.config
# `seo db setup` and the tests pass the URL in; the alembic CLI falls back to .env
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
