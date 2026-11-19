"""HTTP API for the web app: `uv run seo api`, docs at http://localhost:8000/api/docs.

Endpoints (all under /api):

    GET    /health                       is the server up
    GET    /sites                        every site, and which is the default
    POST   /sites                        create a site                 (a SiteConfig)
    GET    /sites/{name}                 one site's settings
    PUT    /sites/{name}                 replace a site's settings     (a SiteConfig)
    DELETE /sites/{name}                 delete a site (its runs stay in the history)
    GET    /sites/{name}/export          the site as a YAML file
    GET    /tools                        every tool, grouped, with whether it's ready
    GET    /tools/{group}/{name}         one tool: description and input JSON Schema
    POST   /runs                         start a run        {tool_id, inputs, site?, refresh?}
    GET    /runs                         run history, newest first
                                         ?tool_id=&status=&site=&limit=&offset=
    GET    /runs/{id}                    one run: status, progress, metrics, notes, error
    GET    /runs/{id}/rows               the results table as columns + rows
    GET    /runs/{id}/download           the results file   ?format=csv|xlsx
    GET    /runs/{id}/report             the written report (Markdown), if any   ?download=1
    GET    /setup                        setup checks for a site      ?site=
    POST   /setup/live                   one real call to each configured API
    …      /documents                    the content editor's drafts (see api/documents.py)

Problems a user can fix (missing key, unknown site) come back as 400 with a plain
`detail` message; a missing site, run or draft is 404; a duplicate site name is 409. Every
invalid request (tool inputs, site settings) is 422 with one error per field:
{"detail": "...", "errors": [{"field": "sections.0.role", "label": "...", "message": "..."}]}.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError

from seo_toolkit import __version__
from seo_toolkit.api.documents import documents_router
from seo_toolkit.api.errors import field_errors, invalid
from seo_toolkit.core import sites as site_store
from seo_toolkit.core.checks import Check, config_checks, live_checks
from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, get_settings
from seo_toolkit.core.db import DatabaseError
from seo_toolkit.core.documents import DocumentNotFound
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.runs import RunManager, RunRecord, Status
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
    page: str | None  # the web app's own screen for this tool, instead of its form


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
        page=tool.page,
    )


def _column_type(series: pd.Series) -> Literal["number", "boolean", "string"]:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    return "string"


def create_app(
    settings: Callable[[], Settings] = get_settings,
    manager: RunManager | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings and run manager."""
    runs = manager or RunManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runs.recover()  # fails here, with the fix in the message, if Postgres is down
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

    @app.exception_handler(site_store.SiteNotFound)
    async def site_not_found(request: Request, error: site_store.SiteNotFound) -> JSONResponse:
        # Asking for a site that isn't there is a 404; *using* one (e.g. in a run) is a 400
        status = 404 if request.url.path.startswith("/api/sites") else 400
        return JSONResponse(status_code=status, content={"detail": str(error)})

    @app.exception_handler(DocumentNotFound)
    async def document_not_found(request: Request, error: DocumentNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(site_store.SiteExists)
    async def site_exists(request: Request, error: site_store.SiteExists) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        model = SiteConfig if request.url.path.startswith("/api/sites") else None
        return invalid(field_errors(error.errors(), model))

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
        sites = site_store.list_sites(current, runs.workspace_id)
        names = [s.name for s in sites]
        default = current.seo_site if current.seo_site in names else (names[0] if names else "")
        summaries = [
            SiteSummary(**s.model_dump(include=set(SiteSummary.model_fields))) for s in sites
        ]
        return Sites(default=default, sites=summaries)

    @app.post("/api/sites", status_code=201)
    def create_site(site: SiteConfig) -> SiteConfig:
        return site_store.create_site(settings(), site, runs.workspace_id)

    @app.get("/api/sites/{name}")
    def get_site(name: str) -> SiteConfig:
        return site_store.load_site(name, settings(), runs.workspace_id)

    @app.put("/api/sites/{name}")
    def update_site(name: str, site: SiteConfig) -> SiteConfig:
        return site_store.update_site(settings(), name, site, runs.workspace_id)

    @app.delete("/api/sites/{name}", status_code=204)
    def delete_site(name: str) -> Response:
        site_store.delete_site(settings(), name, runs.workspace_id)
        return Response(status_code=204)

    @app.get("/api/sites/{name}/export")
    def export_site(name: str) -> Response:
        site = site_store.load_site(name, settings(), runs.workspace_id)
        return Response(
            site_store.site_to_yaml(site),
            media_type="application/yaml",
            headers={"Content-Disposition": f'attachment; filename="{name}.yaml"'},
        )

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

    # A returned JSONResponse (the 422) bypasses response_model; RunRecord types the 202
    @app.post("/api/runs", status_code=202, response_model=RunRecord)
    def start_run(body: StartRun) -> RunRecord | JSONResponse:
        tool = tool_or_404(body.tool_id)
        try:
            inputs = tool.Inputs.model_validate(body.inputs)
        except ValidationError as e:
            return invalid(field_errors(e.errors(), tool.Inputs))
        return runs.start(tool, inputs, site=body.site, refresh=body.refresh)

    @app.get("/api/runs")
    def list_runs(
        tool_id: str | None = None,
        status: Status | None = None,
        site: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[RunRecord]:
        return runs.list(tool_id=tool_id, status=status, site=site, limit=limit, offset=offset)

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

    @app.get("/api/runs/{run_id}/report", response_class=Response)
    def get_report(run_id: str, download: bool = False) -> Response:
        """The run's written report as Markdown (e.g. a content plan)."""
        record = run_or_404(run_id)
        text = runs.report(run_id)
        if text is None:
            raise HTTPException(404, f"Run {run_id} has no report.")
        headers = {}
        if download:
            name = Path(record.report or f"{run_id}.md").name
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return Response(text, media_type="text/markdown; charset=utf-8", headers=headers)

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

    app.include_router(documents_router(settings, runs))
    return app
