"""Command-line entry point: `uv run seo --help`."""

import typer

from seo_toolkit import __version__

app = typer.Typer(help="SEO data analysis and planning toolkit.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """SEO data analysis and planning toolkit."""


@app.command()
def version() -> None:
    """Show the toolkit version."""
    typer.echo(f"seo-toolkit {__version__}")


if __name__ == "__main__":
    app()
