"""The dashboard's pages. Each function draws one page; main.py wires them together."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from seo_toolkit.app import forms
from seo_toolkit.core.checks import ICONS, Check, config_checks, live_checks
from seo_toolkit.core.config import ConfigError, Settings, SiteConfig, get_settings, load_site
from seo_toolkit.core.errors import ToolkitError
from seo_toolkit.tools.base import GROUPS, RunContext, Tool, ToolResult, discover, execute

RESULT_SUFFIXES = (".csv", ".xlsx", ".parquet")


# --- Shared helpers ----------------------------------------------------------------------


def _settings() -> Settings:
    try:
        return get_settings()
    except ConfigError as e:
        st.error(str(e))
        st.stop()
        raise  # unreachable: st.stop() ends the script run


def _site_names(settings: Settings) -> list[str]:
    return sorted(p.stem for p in settings.sites_dir.glob("*.yaml"))


def _current_site(settings: Settings) -> SiteConfig:
    try:
        return load_site(st.session_state.get("site"), settings)
    except ConfigError as e:
        st.error(str(e))
        st.stop()
        raise


def _checks_table(checks: list[Check]) -> None:
    table = pd.DataFrame(
        {
            "": [ICONS[c.status] for c in checks],
            "Area": [c.area for c in checks],
            "Check": [c.name for c in checks],
            "Detail": [c.detail for c in checks],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")


def _relative(path: Path, settings: Settings) -> str:
    try:
        return str(path.relative_to(settings.project_dir))
    except ValueError:
        return str(path)


def sidebar() -> None:
    settings = _settings()
    names = _site_names(settings)
    if not names:
        st.sidebar.error("No site files in config/sites/.")
        return
    if st.session_state.get("site") not in names:
        st.session_state["site"] = settings.seo_site if settings.seo_site in names else names[0]
    st.sidebar.selectbox("Site", names, key="site", help="A file in config/sites/.")
    st.sidebar.toggle(
        "Ignore cache",
        key="refresh",
        help="Fetch fresh data from the APIs instead of reusing stored responses.",
    )


# --- Overview pages ----------------------------------------------------------------------


def home() -> None:
    settings = _settings()
    site = _current_site(settings)
    st.title("SEO Toolkit")
    st.caption("Semantic SEO research and planning tools. Pick a tool from the sidebar.")

    st.subheader(site.domain)
    cols = st.columns(4)
    cols[0].metric("Central entity", site.central_entity or "—")
    cols[1].metric("Entity type", site.entity_type or "—")
    cols[2].metric("Country", site.country.upper())
    cols[3].metric("Language", site.language)
    if site.source_context:
        st.info(f"**Source context:** {site.source_context.strip()}")
    if site.sections:
        st.dataframe(
            pd.DataFrame([s.model_dump() for s in site.sections]),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Tools")
    tools = discover()
    st.dataframe(
        pd.DataFrame(
            {
                "Group": [GROUPS[t.group] for t in tools.values()],
                "Tool": [t.title for t in tools.values()],
                "What it does": [t.summary for t in tools.values()],
                "Ready": [
                    "✅" if not t.missing(settings) else "Needs " + ", ".join(t.missing(settings))
                    for t in tools.values()
                ],
            }
        ),
        hide_index=True,
        width="stretch",
    )

    problems = [c for c in config_checks(settings, site.name) if c.status in ("warn", "fail")]
    if problems:
        st.warning(f"{len(problems)} setup item(s) need attention. See **Setup** in the sidebar.")


def setup() -> None:
    settings = _settings()
    st.title("Setup")
    st.caption("What's configured, and what each key unlocks.")
    _checks_table(config_checks(settings, st.session_state.get("site")))

    st.subheader("Live connection test")
    st.caption(
        "Makes one small real call to each configured API: one Gemini reply, one embedding, "
        "one grounded search (of 5,000 free a month) and one autocomplete request."
    )
    if st.button("Test connections", type="primary"):
        with st.spinner("Calling the APIs…"):
            st.session_state["live_checks"] = live_checks(settings)
    if "live_checks" in st.session_state:
        _checks_table(st.session_state["live_checks"])


def results() -> None:
    settings = _settings()
    st.title("Results")
    st.caption("Every tool run is saved under data/outputs/.")
    files = sorted(
        (p for p in settings.outputs_dir.glob("*/*") if p.suffix in RESULT_SUFFIXES),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        st.info("No results yet. Run a tool and its output will appear here.")
        return

    chosen = st.selectbox(
        "File", files, format_func=lambda p: f"{p.parent.name} / {p.name}", key="results.file"
    )
    readers: dict[str, Callable[[Path], pd.DataFrame]] = {
        ".csv": pd.read_csv,
        ".xlsx": pd.read_excel,
        ".parquet": pd.read_parquet,
    }
    table = readers[chosen.suffix](chosen)
    st.caption(f"{len(table)} rows · {_relative(chosen, settings)}")
    st.dataframe(table, hide_index=True, width="stretch")
    st.download_button("Download", chosen.read_bytes(), file_name=chosen.name)


# --- Tool pages --------------------------------------------------------------------------


def _show_result(result: ToolResult, path: Path | None, settings: Settings) -> None:
    if result.metrics:
        for col, (label, value) in zip(
            st.columns(len(result.metrics)), result.metrics.items(), strict=True
        ):
            col.metric(label, value)
    for note in result.notes:
        st.info(note)
    st.dataframe(result.table, hide_index=True, width="stretch")
    if path:
        st.caption(f"Saved to {_relative(path, settings)}")
    st.download_button(
        "Download CSV",
        result.table.to_csv(index=False).encode(),
        file_name=path.with_suffix(".csv").name if path else "results.csv",
        mime="text/csv",
    )


def tool_page(tool_cls: type[Tool]) -> Callable[[], None]:
    """A page for one tool: its explanation, an input form built from Inputs, and results."""

    def page() -> None:
        settings = _settings()
        st.title(tool_cls.title)
        st.caption(tool_cls.summary)
        with st.expander("How it works"):
            st.markdown(tool_cls.description())

        missing = tool_cls.missing(settings)
        if missing:
            st.warning(f"This tool needs {', '.join(missing)} in your .env file. See **Setup**.")
            return

        with st.form(f"form.{tool_cls.id}"):
            values = forms.input_widgets(tool_cls.Inputs, key=tool_cls.id)
            submitted = st.form_submit_button("Run", type="primary")

        state_key = f"result.{tool_cls.id}"
        if submitted:
            try:
                inputs = tool_cls.Inputs.model_validate(values)
            except ValidationError as e:
                st.error(forms.explain(e, tool_cls.Inputs))
                return
            ctx = RunContext(
                settings, _current_site(settings), refresh=st.session_state.get("refresh", False)
            )
            bar = st.progress(0.0, "Starting…")

            def show_progress(fraction: float, message: str) -> None:
                bar.progress(min(fraction, 1.0), message)

            ctx.progress = show_progress
            try:
                st.session_state[state_key] = execute(tool_cls, inputs, ctx)
            except ToolkitError as e:
                st.error(str(e))
                return
            finally:
                bar.empty()

        if state_key in st.session_state:
            result, path = st.session_state[state_key]
            _show_result(result, path, settings)

    page.__name__ = tool_cls.id.replace("/", "_")  # Streamlit names pages after the function
    return page
