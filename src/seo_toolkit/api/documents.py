"""Content editor endpoints (all under /api/documents):

GET    /                      every draft, newest first (without content)
POST   /                      start a draft: builds its brief in the background
                              {keyword, site?, pages?, import_url?}
GET    /{id}                  one draft, with its content and last answer check
PUT    /{id}                  save the draft (a Draft); its score is stored with it
DELETE /{id}                  delete it
GET    /{id}/brief            the brief's run (for progress) and the brief, once ready
POST   /{id}/brief            rebuild the brief, e.g. from other top pages   {pages?}
POST   /{id}/score            score unsaved text against the brief (a Draft)
POST   /{id}/check-answers    save, then ask Gemini whether each question is answered
GET    /{id}/export           the draft as an HTML file
"""

from __future__ import annotations

import html
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from seo_toolkit.api.errors import field_errors, invalid
from seo_toolkit.connectors.gemini import Gemini
from seo_toolkit.connectors.pages import PageFetcher
from seo_toolkit.core import documents as store
from seo_toolkit.core.config import Settings
from seo_toolkit.core.content import count_words
from seo_toolkit.core.editor import AnswerVerdict, Brief, Score, score_draft
from seo_toolkit.core.output import slugify
from seo_toolkit.core.runs import RunManager, RunRecord
from seo_toolkit.tools.content.content_editor import (
    ContentEditor,
    ContentEditorInputs,
    check_answers,
)


class NewDocument(BaseModel):
    keyword: str
    site: str | None = None
    pages: list[str] = []
    import_url: str | None = None  # an existing page to improve


class RebuildBrief(BaseModel):
    pages: list[str] = []


class BriefState(BaseModel):
    run: RunRecord | None
    brief: Brief | None


def documents_router(settings: Callable[[], Settings], runs: RunManager) -> APIRouter:
    router = APIRouter(prefix="/api/documents")
    workspace = runs.workspace_id
    briefs: dict[str, Brief] = {}  # a finished run's brief never changes

    def brief_for(doc: store.DocumentRecord) -> Brief | None:
        run_id = doc.brief_run_id
        if run_id is None:
            return None
        if run_id not in briefs:
            data = runs.data(run_id)
            if data is None:
                return None
            briefs[run_id] = Brief.model_validate(data)
        return briefs[run_id]

    def ready_brief(doc: store.DocumentRecord) -> Brief:
        brief = brief_for(doc)
        if brief is None:
            raise HTTPException(409, "The brief isn't ready yet. Wait for it to finish.")
        return brief

    def start_brief(keyword: str, pages: list[str], site: str | None) -> RunRecord | JSONResponse:
        try:
            inputs = ContentEditorInputs.model_validate({"keyword": keyword, "pages": pages})
        except ValidationError as e:
            return invalid(field_errors(e.errors(), ContentEditorInputs))
        return runs.start(ContentEditor, inputs, site=site)

    def save(
        doc: store.DocumentRecord,
        draft: store.Draft,
        answers: list[AnswerVerdict] | None = None,
    ) -> store.DocumentRecord:
        brief = brief_for(doc)
        verdicts = answers if answers is not None else doc.answers
        score = (
            score_draft(
                brief, draft.title, draft.meta_description, draft.url_slug, draft.content, verdicts
            ).score
            if brief
            else None
        )
        return store.save_draft(
            settings(),
            doc.id,
            draft,
            score=score,
            word_count=count_words(draft.content),
            answers=answers,
            workspace_id=workspace,
        )

    @router.get("")
    def list_documents() -> list[store.DocumentSummary]:
        return store.list_documents(settings(), workspace)

    # A returned JSONResponse (the 422) bypasses response_model
    @router.post("", status_code=201, response_model=store.DocumentRecord)
    def create_document(body: NewDocument) -> store.DocumentRecord | JSONResponse:
        draft = None
        if body.import_url:
            page = PageFetcher.from_settings(settings()).fetch(body.import_url)
            path = urlsplit(page.final_url).path.strip("/").rsplit("/", 1)[-1]
            draft = store.Draft(
                name=page.title or page.h1 or body.keyword,
                title=page.title,
                meta_description=page.description,
                url_slug=slugify(path),
                content=page.html,
            )
        run = start_brief(body.keyword, body.pages, body.site)
        if isinstance(run, JSONResponse):
            return run
        doc = store.create_document(
            settings(),
            site=run.site,
            keyword=run.inputs["keyword"],
            brief_run_id=run.id,
            draft=draft,
            workspace_id=workspace,
        )
        if draft is not None:
            doc = save(doc, draft)
        return doc

    @router.get("/{doc_id}")
    def get_document(doc_id: str) -> store.DocumentRecord:
        return store.get_document(settings(), doc_id, workspace)

    @router.put("/{doc_id}")
    def save_document(doc_id: str, draft: store.Draft) -> store.DocumentRecord:
        return save(store.get_document(settings(), doc_id, workspace), draft)

    @router.delete("/{doc_id}", status_code=204)
    def delete_document(doc_id: str) -> Response:
        store.delete_document(settings(), doc_id, workspace)
        return Response(status_code=204)

    @router.get("/{doc_id}/brief")
    def get_brief(doc_id: str) -> BriefState:
        doc = store.get_document(settings(), doc_id, workspace)
        run = runs.get(doc.brief_run_id) if doc.brief_run_id else None
        return BriefState(run=run, brief=brief_for(doc))

    @router.post("/{doc_id}/brief", response_model=store.DocumentRecord)
    def rebuild_brief(doc_id: str, body: RebuildBrief) -> store.DocumentRecord | JSONResponse:
        doc = store.get_document(settings(), doc_id, workspace)
        run = start_brief(doc.keyword, body.pages, doc.site)
        if isinstance(run, JSONResponse):
            return run
        return store.set_brief_run(settings(), doc.id, run.id, workspace)

    @router.post("/{doc_id}/score")
    def score(doc_id: str, draft: store.Draft) -> Score:
        doc = store.get_document(settings(), doc_id, workspace)
        return score_draft(
            ready_brief(doc),
            draft.title,
            draft.meta_description,
            draft.url_slug,
            draft.content,
            doc.answers,
        )

    @router.post("/{doc_id}/check-answers")
    def answer_check(doc_id: str, draft: store.Draft) -> store.DocumentRecord:
        doc = store.get_document(settings(), doc_id, workspace)
        brief = ready_brief(doc)
        verdicts = check_answers(Gemini.from_settings(settings()), brief, draft.content)
        return save(doc, draft, verdicts)

    @router.get("/{doc_id}/export")
    def export(doc_id: str) -> Response:
        doc = store.get_document(settings(), doc_id, workspace)
        page = (
            '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(doc.title or doc.name)}</title>\n"
            f'<meta name="description" content="{html.escape(doc.meta_description)}">\n'
            f"</head>\n<body>\n{doc.content}\n</body>\n</html>\n"
        )
        filename = f"{slugify(doc.url_slug or doc.name) or 'draft'}.html"
        return Response(
            page,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
