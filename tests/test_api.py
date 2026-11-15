"""The web app's API, through FastAPI's test client (no server, no network)."""

import io

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


def test_sites(client):
    body = client.get("/api/sites").json()
    assert body["default"] == "example"
    assert body["sites"][0]["central_entity"] == "swimming pool"
    assert client.get("/api/sites/example").json()["sections"][0]["role"] == "core"
    assert client.get("/api/sites/nope").status_code == 404


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
    assert body["detail"] == "Some inputs need fixing."
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
    assert response.status_code == 400 and "No site file" in response.json()["detail"]


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
    assert checks["Site file"]["status"] == "ok"
    assert checks["GEMINI_API_KEY"]["status"] == "off"


def test_database_down_is_503_with_the_fix(project, settings):
    down = Settings(
        _env_file=None, project_dir=project, database_url="postgresql+psycopg://localhost:1/x"
    )
    from seo_toolkit.core.db import DatabaseError

    with pytest.raises(DatabaseError, match="brew services start"):
        RunManager(lambda: down, context_factory=fake_context)  # refuses to start without it

    working = RunManager(lambda: settings, context_factory=fake_context)
    app = create_app(lambda: down, working)
    working._settings = lambda: down  # the database goes away after startup
    with TestClient(app) as client:
        response = client.get("/api/runs")
    assert response.status_code == 503
    assert "brew services start postgresql@17" in response.json()["detail"]
    working.shutdown()
