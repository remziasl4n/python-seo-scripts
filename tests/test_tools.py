import pandas as pd
import pytest
from pydantic import BaseModel

from fakes import FakeAutocomplete
from seo_toolkit.core.config import ConfigError, Settings, load_site
from seo_toolkit.tools.base import RunContext, Tool, ToolResult, discover, execute, get_tool
from seo_toolkit.tools.research.autocomplete import Autocomplete


def test_discover_finds_tools_in_group_order():
    tools = discover()
    assert tools["research/autocomplete"] is Autocomplete
    assert next(iter(tools)).startswith("research/")


def test_get_tool_lists_available_on_typo():
    with pytest.raises(ConfigError, match="research/autocomplete"):
        get_tool("research/autocomplet")


def test_tool_must_declare_its_parts():
    with pytest.raises(TypeError, match="must define `summary`"):

        class Broken(Tool):
            name = "broken"
            group = "research"
            title = "Broken"

            def run(self, inputs, ctx):
                raise NotImplementedError


def test_tool_group_must_be_known():
    with pytest.raises(TypeError, match="group must be one of"):

        class Misfiled(Tool):
            name = "misfiled"
            group = "misc"
            title = "Misfiled"
            summary = "x"
            Inputs = BaseModel

            def run(self, inputs, ctx):
                raise NotImplementedError


def test_description_is_module_docstring():
    assert Autocomplete.description().startswith("Every Google autocomplete suggestion")


class NoInputs(BaseModel):
    pass


def test_missing_lists_env_names(settings):
    class NeedsGemini(Tool):
        name = "needs-gemini-test"
        group = "research"
        title = "Needs Gemini"
        summary = "x"
        needs = ("gemini_api_key",)
        Inputs = NoInputs

        def run(self, inputs, ctx):
            return ToolResult(pd.DataFrame())

    try:
        assert NeedsGemini.missing(settings) == ["GEMINI_API_KEY"]
        with_key = Settings(_env_file=None, project_dir=settings.project_dir, gemini_api_key="k")
        assert NeedsGemini.missing(with_key) == []
        ctx = RunContext(settings, load_site("example", settings))
        with pytest.raises(ConfigError, match="needs GEMINI_API_KEY"):
            execute(NeedsGemini, NoInputs(), ctx)
    finally:
        Tool._registry.pop(NeedsGemini.id)


def test_execute_saves_output(settings):
    ctx = RunContext(
        settings, load_site("example", settings), connectors={"autocomplete": FakeAutocomplete()}
    )
    inputs = Autocomplete.Inputs.model_validate(
        {"seeds": ["pool cost", "pool size"], "expand": "seed only"}
    )
    result, path = execute(Autocomplete, inputs, ctx)
    assert path is not None and path.parent == settings.outputs_dir / "autocomplete"
    assert path.name.endswith("_pool-cost-1.csv")  # first seed, plus how many more
    pd.testing.assert_frame_equal(pd.read_csv(path), result.table, check_dtype=False)


def test_connectors_built_lazily(settings):
    ctx = RunContext(settings, load_site("example", settings))
    assert ctx.connectors == {}
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        ctx.gemini  # noqa: B018
    assert ctx.autocomplete is ctx.autocomplete
