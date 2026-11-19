"""The content editor's API: drafts, their brief, live scores and answer checks."""

import pytest
from fastapi.testclient import TestClient

from fakes import DictAutocomplete, FakeGemini, FakePages
from seo_toolkit.api import documents as documents_api
from seo_toolkit.api.app import create_app
from seo_toolkit.core.config import Settings
from seo_toolkit.core.runs import RunManager
from seo_toolkit.core.sites import load_site
from seo_toolkit.tools.base import RunContext
from test_content_editor import DRAFT, TOP_PAGES, plan_from_prompt


@pytest.fixture
def settings(project):
    return Settings(_env_file=None, project_dir=project, gemini_api_key="test-key")  # type: ignore[call-arg]


@pytest.fixture
def gemini():
    fake = FakeGemini()
    fake.answers["BriefPlan"] = plan_from_prompt
    fake.answers["Verdicts"] = {
        "verdicts": [
            {"question": 1, "status": "answered", "section": 2},
            {
                "question": 2,
                "status": "missing",
                "fix": "Say which permits cities ask for.",
                "place_after": 2,
            },
        ]
    }
    return fake


@pytest.fixture
def client(settings, gemini, monkeypatch):
    def context(settings: Settings, site: str, refresh: bool) -> RunContext:
        return RunContext(
            settings,
            load_site(site, settings),
            refresh,
            connectors={
                "gemini": gemini,
                "pages": FakePages(TOP_PAGES),
                "autocomplete": DictAutocomplete(),
            },
        )

    manager = RunManager(lambda: settings, context_factory=context)
    monkeypatch.setattr(documents_api.Gemini, "from_settings", lambda *a, **k: gemini)
    monkeypatch.setattr(
        documents_api.PageFetcher, "from_settings", lambda *a, **k: FakePages(TOP_PAGES)
    )
    with TestClient(create_app(lambda: settings, manager)) as client:
        client.manager = manager  # type: ignore[attr-defined]
        yield client
    manager.shutdown()


def create(client, **body):
    response = client.post("/api/documents", json={"keyword": "Inground pool cost", **body})
    assert response.status_code == 201, response.text
    doc = response.json()
    client.manager.wait(doc["brief_run_id"], timeout=10)
    return doc


def draft(**fields):
    return {
        "name": "Pool cost",
        "title": "Inground pool cost in 2026: a full price guide",
        "meta_description": "What an inground pool costs.",
        "url_slug": "inground-pool-cost",
        "content": DRAFT,
        **fields,
    }


def test_editor_is_linked_from_the_tools_list(client):
    tool = next(t for t in client.get("/api/tools").json() if t["id"] == "content/content-editor")
    assert tool["page"] == "/editor"
    autocomplete = next(
        t for t in client.get("/api/tools").json() if t["id"] == "research/autocomplete"
    )
    assert autocomplete["page"] is None


def test_a_new_draft_builds_its_brief(client):
    doc = create(client)
    assert (doc["keyword"], doc["name"], doc["site"]) == (
        "inground pool cost",
        "Inground pool cost",
        "example",
    )
    state = client.get(f"/api/documents/{doc['id']}/brief").json()
    assert state["run"]["status"] == "done"
    assert state["brief"]["terms"][0]["term"] == "inground pool cost"
    assert [d["id"] for d in client.get("/api/documents").json()] == [doc["id"]]


def test_saving_stores_the_score_and_word_count(client):
    doc = create(client)
    saved = client.put(f"/api/documents/{doc['id']}", json=draft()).json()
    assert saved["content"] == DRAFT
    assert saved["word_count"] > 50
    assert 0 < saved["score"] <= 100
    listed = client.get("/api/documents").json()[0]
    assert listed["score"] == saved["score"] and "content" not in listed


def test_scoring_unsaved_text(client):
    doc = create(client)
    score = client.post(f"/api/documents/{doc['id']}/score", json=draft()).json()
    assert score["terms"][0]["count"] >= 1
    assert {c["group"] for c in score["checks"]} == {"Main keyword", "Answers", "Easy to read"}
    empty = client.post(f"/api/documents/{doc['id']}/score", json=draft(content="")).json()
    assert empty["score"] < score["score"]
    assert client.get(f"/api/documents/{doc['id']}").json()["content"] == ""  # not saved


def test_answer_check_is_saved_and_shown_in_the_score(client):
    doc = create(client)
    checked = client.post(f"/api/documents/{doc['id']}/check-answers", json=draft()).json()
    assert checked["answers_checked_at"] is not None
    assert checked["answers"][1]["place_after"] == "How much does a fiberglass pool cost?"
    score = client.post(f"/api/documents/{doc['id']}/score", json=draft()).json()
    assert [q["status"] for q in score["questions"]] == ["answered", "missing"]
    assert score["questions"][1]["fix"] == "Say which permits cities ask for."


def test_importing_a_page_to_improve(client):
    doc = create(client, import_url="https://pasted.com/costs/")
    assert doc["title"] == "Pool prices"
    assert "<h2>Excavation</h2>" in doc["content"]
    assert doc["url_slug"] == "costs"
    assert doc["score"] is None  # the brief wasn't ready yet when it was imported


def test_rebuilding_the_brief_from_other_pages(client):
    doc = create(client)
    client.post(f"/api/documents/{doc['id']}/check-answers", json=draft())
    rebuilt = client.post(
        f"/api/documents/{doc['id']}/brief", json={"pages": ["https://pasted.com/costs/"]}
    ).json()
    assert rebuilt["brief_run_id"] != doc["brief_run_id"]
    assert rebuilt["answers"] is None  # the questions may have changed
    client.manager.wait(rebuilt["brief_run_id"], timeout=10)
    brief = client.get(f"/api/documents/{doc['id']}/brief").json()["brief"]
    assert brief["pages"][0]["domain"] == "pasted.com"


def test_export_as_html(client):
    doc = create(client)
    client.put(f"/api/documents/{doc['id']}", json=draft())
    export = client.get(f"/api/documents/{doc['id']}/export")
    assert export.headers["content-disposition"] == 'attachment; filename="inground-pool-cost.html"'
    assert "<title>Inground pool cost in 2026: a full price guide</title>" in export.text
    assert DRAFT in export.text


def test_problems_have_plain_answers(client):
    assert client.get("/api/documents/0123456789abcdef").status_code == 404
    assert client.get("/api/documents/not-an-id").status_code == 404
    bad = client.post("/api/documents", json={"keyword": "pool", "pages": ["nope"]})
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["label"].startswith("Top pages to learn from")
    assert (
        client.post("/api/documents", json={"keyword": "pool", "site": "nope"}).status_code == 400
    )
    doc = create(client)
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404


def test_score_waits_for_the_brief(client, settings):
    from seo_toolkit.core import documents as store

    doc = store.create_document(settings, site="example", keyword="pool cost", brief_run_id=None)
    assert client.post(f"/api/documents/{doc.id}/score", json=draft()).status_code == 409
