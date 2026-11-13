"""Build Streamlit form widgets from a tool's Inputs model.

Each field type gets a widget:

    str              -> text box (empty means "use the default" when the field is optional)
    list[str]        -> text area, one item per line
    int / float      -> number box, respecting ge/le limits
    bool             -> checkbox
    Literal[...]     -> dropdown
"""

from __future__ import annotations

import types
from typing import Any, Literal, Union, get_args, get_origin

import annotated_types
import streamlit as st
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo


def _unwrap_optional(annotation: Any) -> tuple[bool, Any]:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return True, args[0]
    return False, annotation


def _limits(field: FieldInfo) -> dict[str, Any]:
    limits: dict[str, Any] = {}
    for item in field.metadata:
        if isinstance(item, annotated_types.Ge):
            limits["min_value"] = item.ge
        elif isinstance(item, annotated_types.Le):
            limits["max_value"] = item.le
    return limits


def label_for(name: str, field: FieldInfo) -> str:
    return field.title or name.replace("_", " ").capitalize()


def input_widgets(model: type[BaseModel], key: str) -> dict[str, Any]:
    """Draw one widget per field and return the raw values, ready for model_validate."""
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        label = label_for(name, field)
        default = None if field.is_required() else field.get_default(call_default_factory=True)
        optional, kind = _unwrap_optional(field.annotation)
        widget_key = f"{key}.{name}"
        help_text = field.description

        if get_origin(kind) is Literal:
            options = list(get_args(kind))
            index = options.index(default) if default in options else 0
            values[name] = st.selectbox(label, options, index=index, help=help_text, key=widget_key)
        elif kind is bool:
            values[name] = st.checkbox(label, value=bool(default), help=help_text, key=widget_key)
        elif kind in (int, float):
            start = default if default is not None else kind(0)
            values[name] = st.number_input(
                label,
                value=start,
                step=1 if kind is int else 0.1,
                help=help_text,
                key=widget_key,
                **_limits(field),
            )
        elif get_origin(kind) is list:
            text = st.text_area(
                label, value="\n".join(default or []), help=help_text, key=widget_key
            )
            values[name] = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            text = st.text_input(
                label,
                value=default or "",
                help=help_text,
                key=widget_key,
                placeholder="Leave empty to use the default" if optional else None,
            )
            values[name] = text.strip() or (None if optional else "")
    return values


def explain(error: ValidationError, model: type[BaseModel]) -> str:
    """Validation errors as one readable line per field."""
    lines = []
    for e in error.errors():
        name = str(e["loc"][0]) if e["loc"] else ""
        field = model.model_fields.get(name)
        label = label_for(name, field) if field else name
        lines.append(f"- **{label}**: {e['msg'].removeprefix('Value error, ')}")
    return "\n".join(lines)
