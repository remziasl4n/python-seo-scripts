from datetime import datetime

import pandas as pd
import pytest
from rich.console import Console

from seo_toolkit.core.output import output_path, preview, report, save, slugify

NOW = datetime(2026, 11, 11, 9, 30, 0)


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({"query": ["pool cost", "pool size"], "impressions": [120, 80]})


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Swimming Pool Cost (2026)!", "swimming-pool-cost-2026"),
        ("Café crème", "cafe-creme"),
        ("  --a--b--  ", "a-b"),
        ("!!!", ""),
    ],
)
def test_slugify(text, slug):
    assert slugify(text) == slug


def test_slugify_limits_length():
    assert len(slugify("word " * 50)) <= 60
    assert not slugify("word " * 50).endswith("-")


def test_output_path_layout(settings):
    path = output_path("Query Fanout", "swimming pool cost", settings=settings, now=NOW)
    assert (
        path == settings.outputs_dir / "query-fanout" / "2026-11-11_093000_swimming-pool-cost.csv"
    )


def test_output_path_without_slug(settings):
    assert output_path("crawl", None, "xlsx", settings, NOW).name == "2026-11-11_093000.xlsx"


@pytest.mark.parametrize(
    ("fmt", "read"),
    [("csv", pd.read_csv), ("xlsx", pd.read_excel), ("parquet", pd.read_parquet)],
)
def test_save_round_trips(settings, df, fmt, read):
    path = save(df, "query-fanout", "pool", fmt, settings, NOW)
    assert path.suffix == f".{fmt}"
    pd.testing.assert_frame_equal(read(path), df)


def test_same_second_runs_do_not_overwrite(settings, df):
    first = save(df, "crawl", "site", settings=settings, now=NOW)
    second = save(df, "crawl", "site", settings=settings, now=NOW)
    assert first != second
    assert second.name == "2026-11-11_093000_site-2.csv"


def test_unknown_format_rejected(settings, df):
    with pytest.raises(ValueError, match="Unknown format"):
        save(df, "crawl", fmt="json", settings=settings)  # type: ignore[arg-type]


def test_preview_truncates_and_counts_rows():
    console = Console(record=True, width=120)
    big = pd.DataFrame({"text": ["x" * 200] * 25})
    preview(big, rows=10, max_width=20, console=console)
    out = console.export_text()
    assert "Showing 10 of 25 rows" in out
    assert "x" * 19 + "…" in out
    assert "x" * 21 not in out


def test_report_saves_and_says_where(settings, df):
    console = Console(record=True, width=200)
    path = report(df, "query-fanout", "pool cost", settings=settings, console=console)
    assert path.exists()
    out = console.export_text()
    assert "pool cost" in out
    assert "Saved 2 rows to" in out
