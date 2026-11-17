from alembic import command

from seo_toolkit.core import db


def test_migrations_match_the_table_definitions(database_url):
    """A table change in core/db.py without a migration fails here."""
    command.check(db.alembic_config(database_url))


def test_database_reports_ready(settings):
    ready, detail = db.is_ready(settings)
    assert ready, detail
