"""Error responses shared by the API's routes: one plain message per invalid field."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel


class FieldError(BaseModel):
    field: str
    label: str
    message: str


def humanize(name: str) -> str:
    return name.replace("_", " ").capitalize()


def field_errors(
    errors: Sequence[Mapping[str, Any]], model: type[BaseModel] | None
) -> list[FieldError]:
    """Pydantic errors as {field, label, message}. `field` is a dotted path, e.g.
    "sections.0.role"; `label` names it the way the form does, e.g. "Sections, row 1: Role".
    """
    result = []
    for e in errors:
        parts = [str(p) for p in e["loc"]]
        if parts and parts[0] in ("body", "query", "path"):  # where in the request, not a field
            parts = parts[1:]
        if not parts:
            continue
        field = model.model_fields.get(parts[0]) if model else None
        label = field.title if field and field.title else humanize(parts[0])
        if len(parts) >= 2 and parts[1].isdigit():
            label += f", row {int(parts[1]) + 1}"
            if len(parts) > 2:
                label += f": {humanize(parts[2])}"
        message = str(e["msg"]).removeprefix("Value error, ")
        result.append(FieldError(field=".".join(parts), label=label, message=message))
    return result


def invalid(errors: list[FieldError]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Some fields need fixing.", "errors": [e.model_dump() for e in errors]},
    )
