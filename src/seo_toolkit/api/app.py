"""HTTP API for the web app: `uv run seo api`, docs at http://localhost:8000/api/docs.

Endpoints (all under /api):

    GET  /health                         is the server up
    GET  /sites                          site files, and which is the default
    GET  /sites/{name}                   one site's settings
    GET  /tools                          every tool, grouped, with whether it's ready
    GET  /tools/{group}/{name}           one tool: description and input JSON Schema
    POST /runs                           start a run          {tool_id, inputs, site?, refresh?}
    GET  /runs                           run history, newest first   ?tool_id=&limit=
    GET  /runs/{id}                      one run: status, progress, metrics, notes, error
    GET  /runs/{id}/rows                 the results table as columns + rows
    GET  /runs/{id}/download             the results file   ?format=csv|xlsx
    GET  /setup                          setup checks for a site      ?site=
    POST /setup/live                     one real call to each configured API

Problems a user can fix (missing key, bad site file) come back as 400 with a plain
`detail` message. Invalid tool inputs come back as 422 with one error per field.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError

from seo_toolkit import __version__
from seo_toolkit.core.checks import Check, config_checks, live_checks
from seo_toolkit.core.config import ConfigError, Settings, get_settings, load_site
from seo_toolkit.core.db import DatabaseError
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.runs import RunManager, RunRecord
from seo_toolkit.tools.base import GROUPS, Tool, discover

ROW_LIMIT = 50_000  # more than this and the browser table would struggle; download instead


class ToolSummary(BaseModel):
    id: str
    group: str
    group_title: str
    name: str
    title: str
    summary: str
    ready: bool
    missing: list[str]


class ToolDetail(ToolSummary):
    description: str  # markdown
    input_schema: dict[str, Any]


class StartRun(BaseModel):
    tool_id: str
    inputs: dict[str, Any] = {}
    site: str | None = None
    refresh: bool = False


class Column(BaseModel):
    name: str
    type: Literal["number", "boolean", "string"]


class Rows(BaseModel):
    columns: list[Column]
    rows: list[dict[str, Any]]
    total: int
    truncated: bool


class SiteSummary(BaseModel):
    name: str
    domain: str
    central_entity: str
    entity_type: str
    country: str
    language: str


class Sites(BaseModel):
    default: str
    sites: list[SiteSummary]


class FieldError(BaseModel):
    field: str
    label: str
    message: str


def _summary(tool: type[Tool], settings: Settings) -> ToolSummary:
    missing = tool.missing(settings)
    return ToolSummary(
        id=tool.id,
        group=tool.group,
        group_title=GROUPS[tool.group],
        name=tool.name,
        title=tool.title,
        summary=tool.summary,
        ready=not missing,
        missing=missing,
    )


def _column_type(series: pd.Series) -> Literal["number", "boolean", "string"]:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    return "string"


def _field_errors(error: ValidationError, model: type[BaseModel]) -> list[FieldError]:
    errors = []
    for e in error.errors():
        name = str(e["loc"][0]) if e["loc"] else ""
        field = model.model_fields.get(name)
        label = field.title if field and field.title else name.replace("_", " ").capitalize()
        errors.append(
            FieldError(field=name, label=label, message=e["msg"].removeprefix("Value error, "))
        )
    return errors


def create_app(
    settings: Callable[[], Settings] = get_settings,
    manager: RunManager | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings and run manager."""
    runs = manager or RunManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        runs.shutdown()

    app = FastAPI(
        title="SEO Toolkit API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    # The Next.js dev server proxies /api, so this only matters when calling the API directly
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ToolkitError)
    async def toolkit_error(request: Request, error: ToolkitError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(DatabaseError)
    async def database_error(request: Request, error: DatabaseError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    def tool_or_404(tool_id: str) -> type[Tool]:
        tools = discover()
        if tool_id not in tools:
            raise HTTPException(404, f"No tool called {tool_id!r}.")
        return tools[tool_id]

    def run_or_404(run_id: str) -> RunRecord:
        try:
            record = runs.get(run_id)
        except ConfigError:
            record = None
        if record is None:
            raise HTTPException(404, f"No run {run_id!r}.")
        return record

    # --- Sites ----------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/sites")
    def list_sites() -> Sites:
        current = settings()
        sites = []
        for path in sorted(current.sites_dir.glob("*.yaml")):
            try:
                site = load_site(path.stem, current)
            except ConfigError:
                continue  # an invalid file shows up as a failed check on the Setup page
            sites.append(SiteSummary(**site.model_dump(include=set(SiteSummary.model_fields))))
        names = [s.name for s in sites]
        default = current.seo_site if current.seo_site in names else (names[0] if names else "")
        return Sites(default=default, sites=sites)

    @app.get("/api/sites/{name}")
    def get_site(name: str) -> dict[str, Any]:
        current = settings()
        if not (current.sites_dir / f"{name}.yaml").is_file():
            raise HTTPException(404, f"No site file config/sites/{name}.yaml.")
        return load_site(name, current).model_dump()

    # --- Tools ----------------------------------------------------------------------

    @app.get("/api/tools")
    def list_tools() -> list[ToolSummary]:
        current = settings()
        return [_summary(tool, current) for tool in discover().values()]

    @app.get("/api/tools/{group}/{name}")
    def get_tool(group: str, name: str) -> ToolDetail:
        tool = tool_or_404(f"{group}/{name}")
        return ToolDetail(
            **_summary(tool, settings()).model_dump(),
            description=tool.description(),
            input_schema=tool.Inputs.model_json_schema(),
        )

    # --- Runs -----------------------------------------------------------------------

    @app.post("/api/runs", status_code=202, response_model=None)
    def start_run(body: StartRun) -> RunRecord | JSONResponse:
        tool = tool_or_404(body.tool_id)
        try:
            inputs = tool.Inputs.model_validate(body.inputs)
        except ValidationError as e:
            errors = _field_errors(e, tool.Inputs)
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "Some inputs need fixing.",
                    "errors": [err.model_dump() for err in errors],
                },
            )
        return runs.start(tool, inputs, site=body.site, refresh=body.refresh)

    @app.get("/api/runs")
    def list_runs(
        tool_id: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 50
    ) -> list[RunRecord]:
        return runs.list(tool_id=tool_id, limit=limit)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> RunRecord:
        return run_or_404(run_id)

    @app.get("/api/runs/{run_id}/rows")
    def get_rows(run_id: str) -> Rows:
        record = run_or_404(run_id)
        table = runs.table(run_id) if record.status == "done" else None
        if table is None:
            raise HTTPException(409, f"Run {run_id} has no results ({record.status}).")
        shown = table.head(ROW_LIMIT)
        return Rows(
            columns=[Column(name=str(c), type=_column_type(shown[c])) for c in shown.columns],
            rows=json.loads(shown.to_json(orient="records")),  # NaN -> null, numpy -> JSON
            total=len(table),
            truncated=len(table) > ROW_LIMIT,
        )

    @app.get("/api/runs/{run_id}/download", response_model=None)
    def download(run_id: str, format: Literal["csv", "xlsx"] = "csv") -> Response:
        run_or_404(run_id)
        path = runs.output_path(run_id)
        if path is None:
            raise HTTPException(409, f"Run {run_id} has no results file.")
        if path.suffix == f".{format}":
            return FileResponse(path, filename=path.name)
        table = runs.table(run_id)
        assert table is not None
        buffer = io.BytesIO()
        if format == "csv":
            table.to_csv(buffer, index=False)
            media = "text/csv"
        else:
            table.to_excel(buffer, index=False)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{path.stem}.{format}"
        return Response(
            buffer.getvalue(),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # --- Setup ----------------------------------------------------------------------

    @app.get("/api/setup")
    def setup(site: str | None = None) -> list[Check]:
        return config_checks(settings(), site)

    @app.post("/api/setup/live")
    def setup_live() -> list[Check]:
        return live_checks(settings())

    return app
