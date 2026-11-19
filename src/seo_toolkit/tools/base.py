"""The contract every tool follows, and the registry that finds them.

A tool is a class in src/seo_toolkit/tools/<group>/<name>.py:

    class Autocomplete(Tool):
        name = "autocomplete"
        group = "research"
        title = "Autocomplete"
        summary = "Every Google autocomplete suggestion for your seeds."
        needs = ()                      # settings it requires, e.g. ("gemini_api_key",)

        class Inputs(BaseModel):
            seeds: list[str] = Field(description="One per line.")

        def run(self, inputs, ctx) -> ToolResult: ...

The module's docstring is the tool's "How it works" text. The dashboard and the CLI
build their forms from `Inputs`, so a new tool shows up in both without other changes.
A tool with its own screen in the web app (like the content editor) sets `page`.

From a notebook:

    result = run_tool("research/autocomplete", seeds=["pool cost"])
    result.table
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypeVar

import pandas as pd
from pydantic import BaseModel

from seo_toolkit.connectors.autocomplete import AutocompleteClient
from seo_toolkit.connectors.gemini import Gemini
from seo_toolkit.connectors.pages import PageFetcher
from seo_toolkit.core import output
from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, get_settings
from seo_toolkit.core.sites import load_site

# Tool groups in the order the dashboard shows them
GROUPS: dict[str, str] = {
    "research": "Research",
    "content": "Content",
    "performance": "Performance",
    "technical": "Technical",
    "planning": "Planning",
    "ai_search": "AI search",
}

C = TypeVar("C")


@dataclass
class ToolResult:
    table: pd.DataFrame
    metrics: dict[str, int | float | str] = field(default_factory=dict)  # headline numbers
    notes: list[str] = field(default_factory=list)  # things the user should know about the run
    # A plain-language write-up (Markdown) shown above the table, e.g. a content plan.
    # Saved next to the table as <same name>.md.
    report: str | None = None
    # Structured results for a screen of the web app (e.g. the content editor's brief).
    # Saved next to the table as <same name>.data.json.
    data: dict[str, Any] | None = None


def _no_progress(fraction: float, message: str) -> None:
    pass


@dataclass
class RunContext:
    """Everything a tool needs for one run: settings, the site, and connectors.

    Connectors are created on first use, so a tool that never calls Gemini never needs a key.
    Tests pass fakes through `connectors`.
    """

    settings: Settings
    site: SiteConfig
    refresh: bool = False
    progress: Callable[[float, str], None] = _no_progress
    connectors: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls, site: str | None = None, refresh: bool = False, settings: Settings | None = None
    ) -> RunContext:
        settings = settings or get_settings()
        return cls(settings, load_site(site, settings), refresh)

    def _connector(self, name: str, build: Callable[[], C]) -> C:
        if name not in self.connectors:
            self.connectors[name] = build()
        return self.connectors[name]

    @property
    def gemini(self) -> Gemini:
        return self._connector(
            "gemini", lambda: Gemini.from_settings(self.settings, refresh=self.refresh)
        )

    @property
    def autocomplete(self) -> AutocompleteClient:
        return self._connector(
            "autocomplete",
            lambda: AutocompleteClient.from_settings(self.settings, refresh=self.refresh),
        )

    @property
    def pages(self) -> PageFetcher:
        return self._connector(
            "pages", lambda: PageFetcher.from_settings(self.settings, refresh=self.refresh)
        )

    def run_table(self, run_id: str) -> pd.DataFrame:
        """The results table of an earlier run, so one tool can build on another's output."""
        from seo_toolkit.core.runs import RunManager  # runs imports this module

        loader = self.connectors.get("run_table")
        if loader is None:
            manager = RunManager(lambda: self.settings)
            loader = self.connectors["run_table"] = manager.table
        table = loader(run_id)
        if table is None:
            raise ConfigError(f"Run {run_id} has no results to use. Pick a finished run.")
        return table


class Tool(ABC):
    name: ClassVar[str]
    group: ClassVar[str]
    title: ClassVar[str]
    summary: ClassVar[str]
    needs: ClassVar[tuple[str, ...]] = ()
    page: ClassVar[str | None] = None  # the web app's screen for this tool, if not the form
    Inputs: ClassVar[type[BaseModel]]
    id: ClassVar[str]

    _registry: ClassVar[dict[str, type[Tool]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attribute in ("name", "group", "title", "summary", "Inputs"):
            if not hasattr(cls, attribute):
                raise TypeError(f"{cls.__name__} must define `{attribute}`.")
        if cls.group not in GROUPS:
            raise TypeError(f"{cls.__name__}.group must be one of {', '.join(GROUPS)}.")
        cls.id = f"{cls.group}/{cls.name}"
        Tool._registry[cls.id] = cls

    @classmethod
    def description(cls) -> str:
        """The tool module's docstring: what it does and how."""
        return inspect.getdoc(sys.modules[cls.__module__]) or cls.summary

    @classmethod
    def missing(cls, settings: Settings) -> list[str]:
        """The .env variables this tool needs that aren't set."""
        return [name.upper() for name in cls.needs if getattr(settings, name) is None]

    def slug(self, inputs: BaseModel) -> str:
        """A short label for this run's output file: the first text input."""
        for value in inputs.model_dump().values():
            if isinstance(value, str) and value:
                return value
            if isinstance(value, list) and value and isinstance(value[0], str):
                return value[0] + (f" +{len(value) - 1}" if len(value) > 1 else "")
        return ""

    @abstractmethod
    def run(self, inputs: Any, ctx: RunContext) -> ToolResult: ...


def discover() -> dict[str, type[Tool]]:
    """Every tool under seo_toolkit.tools, in dashboard order (by group, then title)."""
    package = importlib.import_module("seo_toolkit.tools")
    for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module.name)
    order = list(GROUPS)
    return dict(
        sorted(Tool._registry.items(), key=lambda item: (order.index(item[1].group), item[1].title))
    )


def get_tool(tool_id: str) -> type[Tool]:
    tools = discover()
    if tool_id not in tools:
        raise ConfigError(f"No tool called {tool_id!r}. Available: {', '.join(tools)}.")
    return tools[tool_id]


def execute(
    tool_cls: type[Tool],
    inputs: BaseModel,
    ctx: RunContext,
    save: bool = True,
    fmt: output.Format = "csv",
) -> tuple[ToolResult, Path | None]:
    """Run a tool and save its table (and report, if any). What the web app and CLI call."""
    missing = tool_cls.missing(ctx.settings)
    if missing:
        raise ConfigError(f"{tool_cls.title} needs {', '.join(missing)} in .env.")
    tool = tool_cls()
    result = tool.run(inputs, ctx)
    path = (
        output.save(result.table, tool_cls.name, tool.slug(inputs), fmt, ctx.settings)
        if save
        else None
    )
    if path is not None and result.report:
        report_path(path).write_text(result.report, encoding="utf-8")
    if path is not None and result.data is not None:
        data_path(path).write_text(json.dumps(result.data, ensure_ascii=False), encoding="utf-8")
    return result, path


def report_path(table_path: Path) -> Path:
    """Where a run's report lives: next to its table, with a .md extension."""
    return table_path.with_suffix(".md")


def data_path(table_path: Path) -> Path:
    """Where a run's structured data lives: next to its table, as .data.json."""
    return table_path.with_suffix(".data.json")


def run_tool(
    tool_id: str, *, site: str | None = None, refresh: bool = False, **inputs: Any
) -> ToolResult:
    """Run a tool from Python (e.g. a notebook) without saving. Inputs are keyword arguments."""
    tool_cls = get_tool(tool_id)
    ctx = RunContext.load(site, refresh)
    result, _ = execute(tool_cls, tool_cls.Inputs.model_validate(inputs), ctx, save=False)
    return result
