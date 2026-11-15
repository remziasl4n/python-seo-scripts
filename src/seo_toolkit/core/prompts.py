"""Prompt templates, kept as editable text files in src/seo_toolkit/prompts/.

    prompt = render("research/query_fanout", query="pool cost", per_type=6, ...)

Templates use $name placeholders (Python's string.Template), so JSON examples and
curly braces in a prompt need no escaping. Edit the .md file to change what a tool asks.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from seo_toolkit.core.errors import ToolkitError

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptError(ToolkitError):
    """A prompt file is missing or uses a placeholder the tool doesn't provide."""


def render(name: str, **values: Any) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"No prompt file at {path}.")
    template = Template(path.read_text(encoding="utf-8"))
    try:
        return template.substitute({k: str(v) for k, v in values.items()}).strip()
    except KeyError as e:
        raise PromptError(
            f"{path.name} uses ${e.args[0]}, which this tool doesn't provide. "
            f"Available: {', '.join('$' + k for k in values)}."
        ) from e
    except ValueError as e:
        raise PromptError(f"{path.name} has a stray $: write $$ for a literal dollar sign.") from e
