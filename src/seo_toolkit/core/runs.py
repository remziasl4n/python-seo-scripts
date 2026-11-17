"""Background tool runs: start a run, follow its progress, read its results later.

    manager = RunManager()
    run = manager.start(QueryFanout, inputs, site="example")
    manager.get(run.id).progress      # 0.0 … 1.0 while it runs
    manager.table(run.id)             # the results table, once done

Run records live in the `runs` table, scoped to a workspace. Progress is written there
too (at most twice a second), so whoever reads a run sees the same thing, including a
separate worker process later. Each run's table is saved in data/outputs/.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update

from seo_toolkit.core.config import ConfigError, Settings, get_settings
from seo_toolkit.core.db import LOCAL_WORKSPACE, Run, session
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.tools.base import RunContext, Tool, execute

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "done", "failed"]
_RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
_READERS: dict[str, Callable[[Path], pd.DataFrame]] = {
    ".csv": pd.read_csv,
    ".xlsx": pd.read_excel,
    ".parquet": pd.read_parquet,
}
PROGRESS_EVERY_SECONDS = 0.5
INTERRUPTED = "Interrupted: the server stopped before this run finished."


def _now() -> datetime:
    return datetime.now(UTC)


class RunRecord(BaseModel):
    """A run as the API and the web app see it."""

    # Every field is always present in API responses, so the generated TypeScript
    # types shouldn't mark fields with defaults (like created_at) as optional
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: str
    workspace_id: str = LOCAL_WORKSPACE
    tool_id: str
    tool_title: str
    site: str
    inputs: dict[str, Any]
    refresh: bool = False
    status: Status = "queued"
    progress: float = 0.0
    message: str = ""
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    metrics: dict[str, int | float | str] = {}
    notes: list[str] = []
    row_count: int | None = None
    output: str | None = None  # results file, relative to the project folder


ContextFactory = Callable[[Settings, str, bool], RunContext]


def _default_context(settings: Settings, site: str, refresh: bool) -> RunContext:
    return RunContext.load(site, refresh, settings)


def _check_id(run_id: str) -> None:
    if not _RUN_ID.match(run_id):
        raise ConfigError(f"{run_id!r} is not a run id.")


class RunManager:
    def __init__(
        self,
        settings: Callable[[], Settings] = get_settings,
        max_workers: int = 2,
        context_factory: ContextFactory = _default_context,
        workspace_id: str = LOCAL_WORKSPACE,
    ) -> None:
        """`settings` is called for every run, so .env changes apply without a restart.

        Creating a manager doesn't touch the database; call `recover()` when a server starts.
        """
        self._settings = settings
        self._context_factory = context_factory
        self.workspace_id = workspace_id
        self._executor = ThreadPoolExecutor(max_workers, thread_name_prefix="seo-run")
        self._futures: dict[str, Future[None]] = {}

    # --- Storage --------------------------------------------------------------------

    def _update(self, run_id: str, **changes: Any) -> None:
        with session(self._settings()) as s:
            s.execute(update(Run).where(Run.id == run_id).values(**changes))

    def recover(self) -> None:
        """Mark runs still queued or running as interrupted: they belonged to a stopped server.

        Fine while one API process runs everything. With separate workers this moves to
        a heartbeat check, so one process can't mark another's runs as interrupted.
        """
        with session(self._settings()) as s:
            s.execute(
                update(Run)
                .where(Run.workspace_id == self.workspace_id, Run.status.in_(["queued", "running"]))
                .values(status="failed", error=INTERRUPTED, finished_at=_now(), message="")
            )

    # --- Running --------------------------------------------------------------------

    def start(
        self,
        tool_cls: type[Tool],
        inputs: BaseModel,
        site: str | None = None,
        refresh: bool = False,
    ) -> RunRecord:
        """Queue a run and return its record at once. Setup problems raise here, not later."""
        settings = self._settings()
        missing = tool_cls.missing(settings)
        if missing:
            raise ConfigError(f"{tool_cls.title} needs {', '.join(missing)} in .env.")
        site_name = site or settings.seo_site
        ctx = self._context_factory(settings, site_name, refresh)  # fails fast on a bad site

        record = RunRecord(
            id=f"{_now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}",
            workspace_id=self.workspace_id,
            tool_id=tool_cls.id,
            tool_title=tool_cls.title,
            site=ctx.site.name,
            inputs=inputs.model_dump(mode="json"),
            refresh=refresh,
            message="Waiting to start…",
        )
        with session(settings) as s:
            s.add(Run(**record.model_dump()))
        self._futures[record.id] = self._executor.submit(
            self._run, record.id, tool_cls, inputs, ctx
        )
        return record

    def _run(self, run_id: str, tool_cls: type[Tool], inputs: BaseModel, ctx: RunContext) -> None:
        self._update(run_id, status="running", started_at=_now(), message="Starting…")
        last_write = 0.0

        def progress(fraction: float, message: str) -> None:
            nonlocal last_write
            if time.monotonic() - last_write < PROGRESS_EVERY_SECONDS and fraction < 1:
                return  # tools can report hundreds of steps; the page polls twice a second
            last_write = time.monotonic()
            self._update(run_id, progress=min(max(fraction, 0.0), 1.0), message=message)

        ctx.progress = progress
        try:
            result, path = execute(tool_cls, inputs, ctx)
        except ToolkitError as e:
            self._update(run_id, status="failed", error=str(e), finished_at=_now(), message="")
        except Exception as e:  # a bug, not a setup problem: keep the details in the log
            log.exception("Run %s (%s) crashed", run_id, tool_cls.id)
            self._update(
                run_id,
                status="failed",
                error=f"Unexpected error: {e!r}. The server log has the details.",
                finished_at=_now(),
                message="",
            )
        else:
            project = ctx.settings.project_dir
            self._update(
                run_id,
                status="done",
                progress=1.0,
                message="Done",
                finished_at=_now(),
                metrics=result.metrics,
                notes=result.notes,
                row_count=len(result.table),
                output=str(path.relative_to(project)) if path else None,
            )

    def wait(self, run_id: str, timeout: float | None = None) -> RunRecord | None:
        """Block until a run started by this manager finishes. Mainly for tests and the CLI."""
        future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout)
        return self.get(run_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --- Reading --------------------------------------------------------------------

    def get(self, run_id: str) -> RunRecord | None:
        _check_id(run_id)
        with session(self._settings()) as s:
            row = s.scalar(
                select(Run).where(Run.id == run_id, Run.workspace_id == self.workspace_id)
            )
            return RunRecord.model_validate(row) if row else None

    def list(
        self,
        tool_id: str | None = None,
        status: Status | None = None,
        site: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """Newest first, optionally filtered. `offset` skips that many for paging."""
        query = select(Run).where(Run.workspace_id == self.workspace_id)
        if tool_id is not None:
            query = query.where(Run.tool_id == tool_id)
        if status is not None:
            query = query.where(Run.status == status)
        if site is not None:
            query = query.where(Run.site == site)
        query = query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset)
        with session(self._settings()) as s:
            return [RunRecord.model_validate(row) for row in s.scalars(query)]

    def output_path(self, run_id: str) -> Path | None:
        record = self.get(run_id)
        if record is None or record.output is None:
            return None
        path = self._settings().project_dir / record.output
        return path if path.is_file() else None

    def table(self, run_id: str) -> pd.DataFrame | None:
        path = self.output_path(run_id)
        if path is None or path.suffix not in _READERS:
            return None
        return _READERS[path.suffix](path)


def import_run_files(settings: Settings, workspace_id: str = LOCAL_WORKSPACE) -> int:
    """Copy run records from data/runs/*.json (before the database) into the runs table.

    Safe to repeat: runs already in the table are skipped. Returns how many were added.
    """
    folder = settings.data_dir / "runs"
    if not folder.is_dir():
        return 0
    added = 0
    with session(settings) as s:
        existing = set(s.scalars(select(Run.id)))
        for path in sorted(folder.glob("*.json")):
            if path.stem in existing or not _RUN_ID.match(path.stem):
                continue
            try:
                record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                log.warning("Skipping unreadable run file %s", path)
                continue
            record.workspace_id = workspace_id
            if record.status in ("queued", "running"):
                record.status, record.error = "failed", INTERRUPTED
            s.add(Run(**record.model_dump()))
            added += 1
    return added
