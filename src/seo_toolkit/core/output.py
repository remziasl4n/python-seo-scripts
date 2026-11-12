"""Save tool results to data/outputs/<tool>/ and print a preview in the terminal.

Every tool ends with:

    report(df, tool="query-fanout", slug="swimming pool cost")

which prints the top rows, saves the full table to
data/outputs/query-fanout/2026-11-11_093000_swimming-pool-cost.csv and prints that path.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from rich.console import Console
from rich.table import Table

from seo_toolkit.core.config import Settings, get_settings

Format = Literal["csv", "xlsx", "parquet"]


def slugify(text: str, max_length: int = 60) -> str:
    """'Swimming Pool Cost (2026)!' -> 'swimming-pool-cost-2026'. Safe for file names."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def output_path(
    tool: str,
    slug: str | None = None,
    fmt: Format = "csv",
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Path:
    """data/outputs/<tool>/<date>_<time>_<slug>.<fmt>, with a counter if the name is taken."""
    settings = settings or get_settings()
    folder = settings.outputs_dir / slugify(tool)
    stem = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    if slug and (clean := slugify(slug)):
        stem = f"{stem}_{clean}"

    path = folder / f"{stem}.{fmt}"
    counter = 2
    while path.exists():
        path = folder / f"{stem}-{counter}.{fmt}"
        counter += 1
    return path


def save(
    df: pd.DataFrame,
    tool: str,
    slug: str | None = None,
    fmt: Format = "csv",
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Path:
    """Write the table to data/outputs/<tool>/ and return the file path."""
    path = output_path(tool, slug, fmt, settings, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "xlsx":
        df.to_excel(path, index=False)
    elif fmt == "parquet":
        df.to_parquet(path, index=False)
    else:
        raise ValueError(f"Unknown format {fmt!r}; use csv, xlsx or parquet.")
    return path


def preview(
    df: pd.DataFrame,
    title: str | None = None,
    rows: int = 10,
    max_width: int = 60,
    console: Console | None = None,
) -> None:
    """Print the first rows as a table. Long cells are cut to `max_width` characters."""
    console = console or Console()
    shown = df.head(rows)
    caption = f"Showing {len(shown)} of {len(df)} rows" if len(df) > rows else None
    table = Table(title=title, caption=caption, show_lines=False)
    for column in shown.columns:
        table.add_column(str(column), overflow="fold")
    for record in shown.itertuples(index=False):
        table.add_row(*(_cell(value, max_width) for value in record))
    console.print(table)


def _cell(value: object, max_width: int) -> str:
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    return text if len(text) <= max_width else text[: max_width - 1] + "…"


def report(
    df: pd.DataFrame,
    tool: str,
    slug: str | None = None,
    fmt: Format = "csv",
    rows: int = 10,
    settings: Settings | None = None,
    console: Console | None = None,
) -> Path:
    """Preview the table, save it, and print where it went. What every tool calls at the end."""
    console = console or Console()
    preview(df, title=f"{tool}: {slug}" if slug else tool, rows=rows, console=console)
    path = save(df, tool, slug, fmt, settings)
    try:
        shown_path = path.relative_to(Path.cwd())
    except ValueError:
        shown_path = path
    console.print(f"Saved {len(df)} rows to [bold]{shown_path}[/bold]")
    return path
