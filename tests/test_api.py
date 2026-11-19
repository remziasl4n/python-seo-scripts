"""The web app's API, through FastAPI's test client (no server, no network)."""

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from seo_toolkit.api.app import create_app
from seo_toolkit.core.config import Settings
from seo_toolkit.core.runs import RunManager
from test_runs import fake_context


@pytest.fixture
def manager(settings):
    manager = RunManager(lambda: settings, context_factory=fake_context)
    yield manager
    manager.shutdown()


@pytest.fixture
def client(settings, manager):
    with TestClient(create_app(lambda: settings, manager)) as client:
        yield client


def start_autocomplete(client, **inputs):
    body = {
        "tool_id": "research/autocomplete",
        "inputs": {"seeds": ["pool cost"], "expand": "seed only", **inputs},
    }
    return client.post("/api/runs", json=body)


def finished(client, manager, response):
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    manager.wait(run_id, timeout=10)
    return client.get(f"/api/runs/{run_id}").json()


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


ACME = {
    "name": "acme",
    "domain": "https://acme.com/",
    "central_entity": "anvil",
    "sections": [{"path": "/anvils/", "name": "Anvils", "role": "core"}],
    "brand_terms": ["acme"],
}


def test_sites(client):
    body = client.get("/api/sites").json()
    assert body["default"] == "example"
    assert body["sites"][0]["central_entity"] == "swimming pool"
    assert client.get("/api/sites/example").json()["sections"][0]["role"] == "core"
    assert client.get("/api/sites/nope").status_code == 404


def test_site_create_update_export_delete(client):
    created = client.post("/api/sites", json=ACME)
    assert created.status_code == 201
    assert created.json()["country"] == "us"  # defaults filled in
    assert [s["name"] for s in client.get("/api/sites").json()["sites"]] == ["acme", "example"]

    assert client.post("/api/sites", json=ACME).status_code == 409  # name taken

    updated = client.put("/api/sites/acme", json={**ACME, "central_entity": "hammer"})
    assert updated.status_code == 200
    assert client.get("/api/sites/acme").json()["central_entity"] == "hammer"
    renamed = client.put("/api/sites/acme", json={**ACME, "name": "acme-2"})
    assert renamed.status_code == 400 and "can't be changed" in renamed.json()["detail"]

    export = client.get("/api/sites/acme/export")
    assert "attachment" in export.headers["content-disposition"]
    assert "central_entity: hammer" in export.text

    assert client.delete("/api/sites/acme").status_code == 204
    assert client.get("/api/sites/acme").status_code == 404
    assert client.delete("/api/sites/acme").status_code == 404


def test_site_validation_errors_name_each_field(client):
    bad = {**ACME, "domain": "acme.com", "sections": [{"path": "anvils", "name": "A", "role": "x"}]}
    response = client.post("/api/sites", json=bad)
    assert response.status_code == 422
    errors = {e["field"]: e for e in response.json()["errors"]}
    assert errors["domain"]["label"] == "Domain"
    assert "full URL" in errors["domain"]["message"]
    assert errors["sections.0.path"]["label"] == "Sections, row 1: Path"
    assert errors["sections.0.role"]["label"] == "Sections, row 1: Role"


def test_running_against_a_missing_site_is_400(client):
    response = client.post(
        "/api/runs",
        json={"tool_id": "research/autocomplete", "inputs": {"seeds": ["x"]}, "site": "ghost"},
    )
    assert response.status_code == 400
    assert "no site called 'ghost'" in response.json()["detail"]


def test_run_history_filters(client, manager):
    finished(client, manager, start_autocomplete(client))
    client.post("/api/sites", json=ACME)
    other = client.post(
        "/api/runs",
        json={
            "tool_id": "research/autocomplete",
            "inputs": {"seeds": ["x"], "expand": "seed only"},
            "site": "acme",
        },
    )
    finished(client, manager, other)

    def ids(**params):
        return [r["site"] for r in client.get("/api/runs", params=params).json()]

    assert ids() == ["acme", "example"]
    assert ids(site="acme") == ["acme"]
    assert ids(status="done") == ["acme", "example"]
    assert ids(status="failed") == []
    assert ids(limit=1, offset=1) == ["example"]
    assert client.get("/api/runs", params={"status": "nonsense"}).status_code == 422


def test_tools_list_says_what_is_ready(client):
    tools = {t["id"]: t for t in client.get("/api/tools").json()}
    assert tools["research/autocomplete"]["ready"] is True
    assert tools["research/query-fanout"]["missing"] == ["GEMINI_API_KEY"]
    assert tools["research/autocomplete"]["group_title"] == "Research"


def test_tool_detail_has_description_and_schema(client):
    tool = client.get("/api/tools/research/autocomplete").json()
    assert tool["description"].startswith("Every Google autocomplete suggestion")
    properties = tool["input_schema"]["properties"]
    assert properties["seeds"]["title"] == "Seed queries"
    assert properties["expand"]["default"] == "everything"
    assert client.get("/api/tools/research/nope").status_code == 404


def test_run_lifecycle_rows_and_downloads(client, manager):
    run = finished(client, manager, start_autocomplete(client))
    assert run["status"] == "done"
    assert run["metrics"]["Suggestions"] == 3

    rows = client.get(f"/api/runs/{run['id']}/rows").json()
    assert {c["name"]: c["type"] for c in rows["columns"]}["times_seen"] == "number"
    assert {c["name"]: c["type"] for c in rows["columns"]}["is_brand"] == "boolean"
    assert rows["total"] == 3 and not rows["truncated"]
    assert rows["rows"][0]["suggestion"] == "pool cost texas"  # seed only: Google's order

    csv = client.get(f"/api/runs/{run['id']}/download")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "suggestion" in csv.text.splitlines()[0]
    xlsx = client.get(f"/api/runs/{run['id']}/download", params={"format": "xlsx"})
    assert pd.read_excel(io.BytesIO(xlsx.content))["suggestion"].iloc[0] == "pool cost texas"

    history = client.get("/api/runs", params={"tool_id": "research/autocomplete"}).json()
    assert [r["id"] for r in history] == [run["id"]]


def test_invalid_inputs_come_back_per_field(client):
    response = client.post(
        "/api/runs", json={"tool_id": "research/autocomplete", "inputs": {"seeds": []}}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Some fields need fixing."
    assert body["errors"][0]["field"] == "seeds"
    assert body["errors"][0]["label"] == "Seed queries"


def test_setup_problems_are_400_with_a_plain_message(client):
    response = client.post(
        "/api/runs", json={"tool_id": "research/query-fanout", "inputs": {"query": "pool cost"}}
    )
    assert response.status_code == 400
    assert "GEMINI_API_KEY" in response.json()["detail"]
    response = client.post(
        "/api/runs",
        json={"tool_id": "research/autocomplete", "inputs": {"seeds": ["x"]}, "site": "nope"},
    )
    assert response.status_code == 400 and "no site called" in response.json()["detail"]


def test_unknown_things_are_404(client):
    assert client.post("/api/runs", json={"tool_id": "research/nope"}).status_code == 404
    assert client.get("/api/runs/20260101-000000-abcdef").status_code == 404
    assert client.get("/api/runs/not-a-run-id").status_code == 404


def test_rows_without_a_results_file_are_409(client, manager, settings):
    run = finished(client, manager, start_autocomplete(client))
    assert client.get(f"/api/runs/{run['id']}/rows").status_code == 200
    (settings.project_dir / run["output"]).unlink()  # results file gone
    assert client.get(f"/api/runs/{run['id']}/rows").status_code == 409


def test_setup_checks(client):
    checks = {c["name"]: c for c in client.get("/api/setup").json()}
    assert checks["Site"]["status"] == "ok"
    assert checks["GEMINI_API_KEY"]["status"] == "off"


def test_database_down_is_503_with_the_fix(project, settings):
    down = Settings(
        _env_file=None, project_dir=project, database_url="postgresql+psycopg://localhost:1/x"
    )
    from seo_toolkit.core.db import DatabaseError

    # The server refuses to start without it
    broken = create_app(lambda: down, RunManager(lambda: down, context_factory=fake_context))
    with pytest.raises(DatabaseError, match="brew services start"), TestClient(broken):
        pass

    # ...and if it goes away while running, requests get a 503 with the fix
    working = RunManager(lambda: settings, context_factory=fake_context)
    with TestClient(create_app(lambda: down, working)) as client:
        working._settings = lambda: down
        response = client.get("/api/runs")
    assert response.status_code == 503
    assert "brew services start postgresql@17" in response.json()["detail"]


def test_app_can_be_built_without_a_database(project):
    """`seo openapi` builds the app just to read its schema: that mustn't need Postgres."""
    down = Settings(
        _env_file=None, project_dir=project, database_url="postgresql+psycopg://localhost:1/x"
    )
    schema = create_app(lambda: down).openapi()
    assert "/api/runs" in schema["paths"]


def test_committed_openapi_schema_is_up_to_date():
    """web/src/lib/api/openapi.json drives the front end's types. Regenerate it with
    `cd web && pnpm gen:api` after changing the API."""
    from conftest import REPO

    committed = json.loads((REPO / "web/src/lib/api/openapi.json").read_text())
    assert committed == create_app().openapi(), "Run: cd web && pnpm gen:api"


def test_report_endpoint(client, manager):
    from test_runs import ReportingTool  # noqa: F401  (registers the tool)

    run = finished(
        client, manager, client.post("/api/runs", json={"tool_id": "planning/reporting-test"})
    )
    report = client.get(f"/api/runs/{run['id']}/report")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert report.text.startswith("# Plan")
    download = client.get(f"/api/runs/{run['id']}/report", params={"download": 1})
    assert download.headers["content-disposition"].endswith('.md"')

    plain = finished(client, manager, start_autocomplete(client))
    assert plain["report"] is None
    assert client.get(f"/api/runs/{plain['id']}/report").status_code == 404
