"""Drafts written in the content editor, stored in Postgres per workspace.

doc = create_document(settings, site="example", keyword="pool cost", brief_run_id=run.id)
save_draft(settings, doc.id, Draft(name=..., content="<h1>…</h1>"), score=72)
list_documents(settings)            # newest first, without their content
get_document(settings, doc.id)
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from seo_toolkit.core.config import ConfigError, Settings
from seo_toolkit.core.db import LOCAL_WORKSPACE, Document, session
from seo_toolkit.core.editor import AnswerVerdict

_ID = re.compile(r"^[0-9a-f]{16}$")
MAX_CONTENT = 2_000_000  # characters of HTML: far more than any real page


class DocumentNotFound(ConfigError):
    """No draft with that id in this workspace."""


class Draft(BaseModel):
    """What the editor saves."""

    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=1000)
    url_slug: str = Field(default="", max_length=300)
    content: str = Field(default="", max_length=MAX_CONTENT)  # HTML


class DocumentSummary(BaseModel):
    # Every field is always present in responses, so generated TypeScript types mark none
    # of them optional (see RunRecord)
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: str
    site: str
    keyword: str
    name: str
    brief_run_id: str | None
    score: int | None
    word_count: int
    created_at: datetime
    updated_at: datetime


class DocumentRecord(DocumentSummary):
    title: str
    meta_description: str
    url_slug: str
    content: str
    answers: list[AnswerVerdict] | None
    answers_checked_at: datetime | None


def _now() -> datetime:
    return datetime.now(UTC)


def _check_id(doc_id: str) -> None:
    if not _ID.match(doc_id):
        raise DocumentNotFound(f"There's no draft {doc_id!r}.")


def create_document(
    settings: Settings,
    *,
    site: str,
    keyword: str,
    brief_run_id: str | None,
    draft: Draft | None = None,
    workspace_id: str = LOCAL_WORKSPACE,
) -> DocumentRecord:
    draft = draft or Draft(name=keyword[:1].upper() + keyword[1:])
    now = _now()
    row = Document(
        id=secrets.token_hex(8),
        workspace_id=workspace_id,
        site=site,
        keyword=keyword,
        brief_run_id=brief_run_id,
        answers=None,
        answers_checked_at=None,
        score=None,
        word_count=0,
        created_at=now,
        updated_at=now,
        **draft.model_dump(),
    )
    with session(settings) as s:
        s.add(row)
        s.flush()
        return DocumentRecord.model_validate(row)


def list_documents(
    settings: Settings, workspace_id: str = LOCAL_WORKSPACE, limit: int = 200
) -> list[DocumentSummary]:
    query = (
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.updated_at.desc())
        .limit(limit)
    )
    with session(settings) as s:
        return [DocumentSummary.model_validate(row) for row in s.scalars(query)]


def _row(s: Session, doc_id: str, workspace_id: str) -> Document:
    _check_id(doc_id)
    row = s.scalar(
        select(Document).where(Document.id == doc_id, Document.workspace_id == workspace_id)
    )
    if row is None:
        raise DocumentNotFound(f"There's no draft {doc_id!r}. It may have been deleted.")
    return row


def get_document(
    settings: Settings, doc_id: str, workspace_id: str = LOCAL_WORKSPACE
) -> DocumentRecord:
    with session(settings) as s:
        return DocumentRecord.model_validate(_row(s, doc_id, workspace_id))


def save_draft(
    settings: Settings,
    doc_id: str,
    draft: Draft,
    *,
    score: int | None,
    word_count: int,
    answers: list[AnswerVerdict] | None = None,
    workspace_id: str = LOCAL_WORKSPACE,
) -> DocumentRecord:
    """Save what the editor holds. `answers` (from an answer check) replaces the last ones."""
    with session(settings) as s:
        row = _row(s, doc_id, workspace_id)
        for field, value in draft.model_dump().items():
            setattr(row, field, value)
        row.score = score
        row.word_count = word_count
        if answers is not None:
            row.answers = [a.model_dump() for a in answers]
            row.answers_checked_at = _now()
        row.updated_at = _now()
        s.flush()
        return DocumentRecord.model_validate(row)


def set_brief_run(
    settings: Settings, doc_id: str, run_id: str, workspace_id: str = LOCAL_WORKSPACE
) -> DocumentRecord:
    """Point a draft at a new brief (e.g. rebuilt from other top pages)."""
    with session(settings) as s:
        row = _row(s, doc_id, workspace_id)
        row.brief_run_id = run_id
        row.answers = None  # the questions may have changed
        row.answers_checked_at = None
        row.updated_at = _now()
        s.flush()
        return DocumentRecord.model_validate(row)


def delete_document(settings: Settings, doc_id: str, workspace_id: str = LOCAL_WORKSPACE) -> None:
    with session(settings) as s:
        s.delete(_row(s, doc_id, workspace_id))
