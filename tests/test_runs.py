import threading

import pandas as pd
import pytest
from pydantic import BaseModel

from fakes import FakeAutocomplete
from seo_toolkit.core.config import ConfigError, Settings
from seo_toolkit.core.db import Run as RunRow
from seo_toolkit.core.db import Workspace as WorkspaceRow
from seo_toolkit.core.db import session
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.core.runs import RunManager, RunRecord, import_run_files
from seo_toolkit.core.sites import load_site
from seo_toolkit.tools.base import RunContext, Tool, ToolResult
from seo_toolkit.tools.research.autocomplete import Autocomplete
from seo_toolkit.tools.research.query_fanout import QueryFanout


class NoInputs(BaseModel):
    pass


class Gate:
    """Lets a test hold a run in the middle, then release it."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()


GATE = Gate()


class BlockingTool(Tool):
    name = "blocking-test"
    group = "research"
    title = "Blocking"
    summary = "Waits for the test."
    Inputs = NoInputs

    def run(self, inputs, ctx):
        ctx.progress(0.4, "Halfway")
        GATE.reached.set()
        GATE.release.wait(5)
        return ToolResult(pd.DataFrame({"a": [1, 2]}), {"Rows": 2}, ["a note"])


class FailingTool(Tool):
    name = "failing-test"
    group = "research"
    title = "Failing"
    summary = "Raises."
    Inputs = NoInputs
    error: Exception = ToolkitError("Add a key first.")

    def run(self, inputs, ctx):
        raise type(self).error


class ReportingTool(Tool):
    name = "reporting-test"
    group = "planning"
    title = "Reporting"
    summary = "Returns a table and a written plan."
    Inputs = NoInputs

    def run(self, inputs, ctx):
        return ToolResult(
            pd.DataFrame({"keyword": ["pool cost"]}), report="# Plan\n\n- [ ] Write it\n"
        )


class DataTool(Tool):
    name = "data-test"
    group = "content"
    title = "Data"
    summary = "Returns a table and data for a screen of the web app."
    Inputs = NoInputs

    def run(self, inputs, ctx):
        return ToolResult(pd.DataFrame({"term": ["pool"]}), data={"terms": ["pool"], "n": 1})


@pytest.fixture(autouse=True)
def _unregister_test_tools():
    yield
    for tool in (BlockingTool, FailingTool, ReportingTool, DataTool):
        Tool._registry.pop(tool.id, None)


def test_reports_are_saved_next_to_the_table(manager, settings):
    run = manager.wait(manager.start(ReportingTool, NoInputs()).id, timeout=5)
    assert run is not None and run.status == "done"
    assert run.output and run.report == run.output.removesuffix(".csv") + ".md"
    assert (settings.project_dir / run.report).read_text() == "# Plan\n\n- [ ] Write it\n"
    assert manager.report(run.id) == "# Plan\n\n- [ ] Write it\n"
    plain = manager.wait(manager.start(Autocomplete, autocomplete_inputs()).id, timeout=5)
    assert plain is not None and plain.report is None and manager.report(plain.id) is None


def test_data_is_saved_next_to_the_table(manager, settings):
    run = manager.wait(manager.start(DataTool, NoInputs()).id, timeout=5)
    assert run is not None and run.status == "done" and run.output
    assert (settings.project_dir / run.output.replace(".csv", ".data.json")).is_file()
    assert manager.data(run.id) == {"terms": ["pool"], "n": 1}
    plain = manager.wait(manager.start(Autocomplete, autocomplete_inputs()).id, timeout=5)
    assert plain is not None and manager.data(plain.id) is None


def fake_context(settings: Settings, site: str, refresh: bool) -> RunContext:
    return RunContext(
        settings,
        load_site(site, settings),
        refresh,
        connectors={"autocomplete": FakeAutocomplete()},
    )


@pytest.fixture
def manager(settings):
    manager = RunManager(lambda: settings, context_factory=fake_context)
    yield manager
    manager.shutdown()


def autocomplete_inputs(seed="pool cost"):
    return Autocomplete.Inputs.model_validate({"seeds": [seed], "expand": "seed only"})


def test_run_completes_and_is_saved(manager, settings):
    started = manager.start(Autocomplete, autocomplete_inputs(), site="example")
    assert started.status == "queued"
    assert started.inputs == {
        "seeds": ["pool cost"],
        "expand": "seed only",
        "country": None,
        "language": None,
    }

    done = manager.wait(started.id, timeout=10)
    assert done is not None and done.status == "done"
    assert done.progress == 1.0
    assert done.row_count == 3
    assert done.metrics["Suggestions"] == 3
    assert done.output and done.output.startswith("data/outputs/autocomplete/")
    assert manager.table(done.id)["suggestion"].tolist()[0] == "pool cost texas"
    # Stored in the database, so a fresh manager (e.g. after a restart) sees it
    fresh = RunManager(lambda: settings, context_factory=fake_context)
    assert fresh.get(done.id) == done
    fresh.shutdown()


def test_progress_is_visible_while_running(manager):
    GATE.reached.clear()
    GATE.release.clear()
    run = manager.start(BlockingTool, NoInputs())
    assert GATE.reached.wait(5)
    live = manager.get(run.id)
    assert live is not None
    assert (live.status, live.progress, live.message) == ("running", 0.4, "Halfway")
    GATE.release.set()
    done = manager.wait(run.id, timeout=5)
    assert done is not None and (done.status, done.notes) == ("done", ["a note"])


def test_setup_errors_raise_before_queueing(manager):
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        manager.start(QueryFanout, QueryFanout.Inputs(query="pool cost"))
    with pytest.raises(ConfigError, match="no site called"):
        manager.start(Autocomplete, autocomplete_inputs(), site="nope")
    assert manager.list() == []


def test_user_fixable_error_is_shown_as_is(manager):
    FailingTool.error = ToolkitError("Add a key first.")
    run = manager.wait(manager.start(FailingTool, NoInputs()).id, timeout=5)
    assert run is not None
    assert (run.status, run.error) == ("failed", "Add a key first.")


def test_crash_is_reported_without_killing_the_manager(manager):
    FailingTool.error = ZeroDivisionError("oops")
    run = manager.wait(manager.start(FailingTool, NoInputs()).id, timeout=5)
    assert run is not None and run.status == "failed"
    assert run.error is not None and run.error.startswith("Unexpected error: ZeroDivisionError")
    after = manager.wait(manager.start(Autocomplete, autocomplete_inputs()).id, timeout=5)
    assert after is not None and after.status == "done"


def test_list_is_newest_first_and_filters(manager):
    first = manager.wait(manager.start(Autocomplete, autocomplete_inputs("a")).id, timeout=5)
    second = manager.wait(manager.start(Autocomplete, autocomplete_inputs("b")).id, timeout=5)
    FailingTool.error = ToolkitError("x")
    manager.wait(manager.start(FailingTool, NoInputs()).id, timeout=5)
    assert first and second
    listed = manager.list(tool_id="research/autocomplete")
    assert {r.id for r in listed} == {first.id, second.id}
    assert len(manager.list()) == 3
    assert len(manager.list(limit=1)) == 1


def test_unfinished_runs_are_marked_interrupted_on_restart(settings, manager):
    GATE.reached.clear()
    GATE.release.clear()
    run = manager.start(BlockingTool, NoInputs())
    GATE.reached.wait(5)
    restarted = RunManager(lambda: settings, context_factory=fake_context)
    assert restarted.get(run.id).status == "running"  # creating a manager changes nothing
    restarted.recover()  # what a starting server does
    record = restarted.get(run.id)
    assert record is not None and record.status == "failed"
    assert record.error is not None and "Interrupted" in record.error
    GATE.release.set()
    restarted.shutdown()


def test_bad_run_ids_are_rejected(manager):
    with pytest.raises(ConfigError):
        manager.get("../../etc/passwd")
    assert manager.get("20260101-000000-abcdef") is None


def test_runs_are_scoped_to_a_workspace(settings, manager):
    run = manager.wait(manager.start(Autocomplete, autocomplete_inputs()).id, timeout=5)
    assert run is not None and run.workspace_id == "local"
    with session(settings) as s:
        s.merge(WorkspaceRow(id="acme", name="Acme"))
    other = RunManager(lambda: settings, context_factory=fake_context, workspace_id="acme")
    assert other.get(run.id) is None
    assert other.list() == []
    other.shutdown()


def test_progress_is_written_to_the_database(settings, manager):
    GATE.reached.clear()
    GATE.release.clear()
    run = manager.start(BlockingTool, NoInputs())
    assert GATE.reached.wait(5)
    # Read the row directly, as a separate process would
    with session(settings) as s:
        row = s.get(RunRow, run.id)
        assert row is not None
        assert (row.status, row.progress, row.message) == ("running", 0.4, "Halfway")
    GATE.release.set()
    manager.wait(run.id, timeout=5)


def test_old_run_files_are_imported_once(settings, manager):
    folder = settings.data_dir / "runs"
    folder.mkdir(parents=True)
    done = RunRecord(
        id="20261101-120000-aaaaaa",
        tool_id="research/autocomplete",
        tool_title="Autocomplete",
        site="example",
        inputs={"seeds": ["x"]},
        status="done",
        row_count=4,
    )
    stuck = done.model_copy(update={"id": "20261101-130000-bbbbbb", "status": "running"})
    (folder / f"{done.id}.json").write_text(done.model_dump_json())
    (folder / f"{stuck.id}.json").write_text(stuck.model_dump_json())
    (folder / "20261101-140000-cccccc.json").write_text("{broken")

    assert import_run_files(settings) == 2
    assert import_run_files(settings) == 0  # already there
    assert manager.get(done.id).row_count == 4
    imported_stuck = manager.get(stuck.id)
    assert imported_stuck.status == "failed" and "Interrupted" in imported_stuck.error
