"""Command-line entry point: `uv run seo --help`."""

import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, get_origin

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from seo_toolkit import __version__
from seo_toolkit.core import output
from seo_toolkit.core.checks import ICONS, config_checks, live_checks
from seo_toolkit.core.config import get_settings
from seo_toolkit.core.errors import ToolkitError

app = typer.Typer(help="SEO data analysis and planning toolkit.", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """SEO data analysis and planning toolkit."""


@app.command()
def version() -> None:
    """Show the toolkit version."""
    typer.echo(f"seo-toolkit {__version__}")


@app.command("app")
def run_app(port: Annotated[int, typer.Option(help="Port to serve on.")] = 8501) -> None:
    """Open the dashboard in your browser (http://localhost:8501)."""
    script = Path(__file__).parent / "app" / "main.py"
    command = [sys.executable, "-m", "streamlit", "run", str(script), "--server.port", str(port)]
    # Only this computer can open it: the app can spend your API quota
    command += ["--server.address", "localhost", "--browser.gatherUsageStats", "false"]
    raise typer.Exit(subprocess.call(command))


@app.command()
def doctor(
    site: Annotated[str | None, typer.Option(help="Site file to check.")] = None,
    live: Annotated[
        bool, typer.Option("--live", help="Also make one small real call to each API.")
    ] = False,
) -> None:
    """Check settings, site file and API keys."""
    try:
        settings = get_settings()
    except ToolkitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    checks = config_checks(settings, site)
    if live:
        with console.status("Calling the APIs…"):
            checks += live_checks(settings)
    table = Table("", "Area", "Check", "Detail", show_lines=False)
    for c in checks:
        table.add_row(ICONS[c.status], c.area, c.name, c.detail)
    console.print(table)
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


@app.command("tools")
def list_tools() -> None:
    """List every tool and whether it's ready to run."""
    from seo_toolkit.tools.base import discover

    settings = get_settings()
    table = Table("Tool", "What it does", "Ready")
    for tool in discover().values():
        missing = tool.missing(settings)
        table.add_row(tool.id, tool.summary, "✅" if not missing else "needs " + ", ".join(missing))
    console.print(table)


def _parse_inputs(pairs: list[str], fields: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"{pair!r} should look like name=value.")
        if name not in fields:
            raise typer.BadParameter(f"Unknown input {name!r}. Inputs: {', '.join(fields)}.")
        if get_origin(fields[name].annotation) is list:
            values.setdefault(name, []).append(value)  # repeat the name for more items
        else:
            values[name] = value
    return values


@app.command("run")
def run_tool_command(
    tool_id: Annotated[str, typer.Argument(help="e.g. research/autocomplete")],
    inputs: Annotated[
        list[str] | None,
        typer.Argument(help='name=value pairs, e.g. seeds="pool cost" seeds="pool size"'),
    ] = None,
    site: Annotated[str | None, typer.Option(help="Site file to use.")] = None,
    refresh: Annotated[bool, typer.Option(help="Ignore cached API responses.")] = False,
    fmt: Annotated[str, typer.Option("--format", help="csv, xlsx or parquet.")] = "csv",
) -> None:
    """Run a tool, preview the results and save them to data/outputs/."""
    from seo_toolkit.tools.base import RunContext, execute, get_tool

    try:
        tool_cls = get_tool(tool_id)
        parsed = tool_cls.Inputs.model_validate(
            _parse_inputs(inputs or [], tool_cls.Inputs.model_fields)
        )
        ctx = RunContext.load(site, refresh)
        with console.status("Running…") as status:
            ctx.progress = lambda fraction, message: status.update(f"{fraction:.0%} {message}")
            result, path = execute(tool_cls, parsed, ctx, fmt=fmt)  # type: ignore[arg-type]
    except ValidationError as e:
        console.print(f"[red]Invalid inputs:[/red]\n{e}")
        raise typer.Exit(1) from e
    except ToolkitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    output.preview(result.table, title=tool_cls.title, console=console)
    for label, value in result.metrics.items():
        console.print(f"{label}: [bold]{value}[/bold]")
    for note in result.notes:
        console.print(f"[yellow]{note}[/yellow]")
    console.print(f"Saved {len(result.table)} rows to [bold]{path}[/bold]")


if __name__ == "__main__":
    app()
