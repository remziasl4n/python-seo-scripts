"""Command-line entry point: `uv run seo --help`."""

import json
import os
import shutil
import subprocess
import sys
import time
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


@app.command("api")
def run_api(
    port: Annotated[int, typer.Option(help="Port to serve on.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Restart when Python code changes.")] = True,
) -> None:
    """Start the web app's API (docs at http://localhost:8000/api/docs)."""
    import uvicorn

    from seo_toolkit.core.db import is_ready

    ready, detail = is_ready(get_settings())
    if not ready:
        console.print(f"[red]{detail}[/red]")
        raise typer.Exit(1)

    # 127.0.0.1 only: the API can spend your API quota, so nothing else on the network gets in
    uvicorn.run(
        "seo_toolkit.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
    )


@app.command("openapi")
def openapi_schema(
    output_file: Annotated[Path, typer.Argument(help="Where to write the JSON schema.")],
) -> None:
    """Write the API's OpenAPI schema. The web app generates its TypeScript types from it."""
    from seo_toolkit.api.app import create_app

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
    console.print(f"Wrote {output_file}")


@app.command("dev")
def dev(
    api_port: Annotated[int, typer.Option(help="Port for the API.")] = 8000,
    web_port: Annotated[int, typer.Option(help="Port for the web app.")] = 3000,
) -> None:
    """Start the API and the web app together: http://localhost:3000. Ctrl+C stops both."""
    from seo_toolkit.core.db import is_ready

    settings = get_settings()
    web = settings.project_dir / "web"
    ready, detail = is_ready(settings)
    if not ready:
        console.print(f"[red]{detail}[/red]")
        raise typer.Exit(1)
    if shutil.which("corepack") is None:
        console.print("[red]Node.js isn't installed. Install it with: brew install node[/red]")
        raise typer.Exit(1)
    pnpm = ["corepack", "pnpm"]
    # corepack fetches the pnpm version pinned in web/package.json without asking
    node_env = {**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    if not (web / "node_modules").is_dir():
        console.print("Installing the web app's packages (first run only)…")
        if subprocess.call([*pnpm, "install"], cwd=web, env=node_env) != 0:
            raise typer.Exit(1)

    api = subprocess.Popen(
        [sys.executable, "-m", "seo_toolkit.cli", "api", "--port", str(api_port)]
    )
    web_env = {**node_env, "PORT": str(web_port), "SEO_API_URL": f"http://127.0.0.1:{api_port}"}
    site = subprocess.Popen([*pnpm, "dev"], cwd=web, env=web_env)
    console.print(f"\n[bold]Open http://localhost:{web_port}[/bold]  (Ctrl+C stops both)\n")
    try:
        while api.poll() is None and site.poll() is None:  # stop both if either stops
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (site, api):
            if process.poll() is None:
                process.terminate()
        for process in (site, api):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@app.command("app")
def run_app(
    api_port: Annotated[int, typer.Option(help="Port for the API.")] = 8000,
    web_port: Annotated[int, typer.Option(help="Port for the web app.")] = 3000,
) -> None:
    """Open the web app (http://localhost:3000). The same as `seo dev`."""
    dev(api_port=api_port, web_port=web_port)


db_app = typer.Typer(help="Set up and update the database.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("setup")
def db_setup() -> None:
    """Create the database if needed, bring its tables up to date, and import
    config/sites/*.yaml and old run files. Safe to repeat: nothing is imported twice."""
    from seo_toolkit.core.db import setup_database
    from seo_toolkit.core.runs import import_run_files
    from seo_toolkit.core.sites import import_site_files

    settings = get_settings()
    try:
        created = setup_database(settings)
        sites, problems = import_site_files(settings)
        imported = import_run_files(settings)
    except ToolkitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    name = settings.database_url.rsplit("/", 1)[-1]
    console.print(f"{'Created' if created else 'Found'} database {name}; tables are up to date.")
    if sites:
        console.print(f"Imported site(s) from config/sites/: {', '.join(sites)}.")
    for problem in problems:
        console.print(f"[yellow]Skipped: {problem}[/yellow]")
    if imported:
        console.print(f"Imported {imported} earlier run(s) from data/runs/.")


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
        with console.status("Calling the APIs…") as status:
            checks += live_checks(settings, on_step=lambda step: status.update(f"Testing {step}"))
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
