"""Gemini connector tests, against a fake client that returns real SDK response objects."""

import hashlib
from typing import Any

import numpy as np
import pytest
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import wait_none

from seo_toolkit.connectors.gemini import Gemini, GeminiError, GroundedAnswer
from seo_toolkit.core.cache import Cache
from seo_toolkit.core.config import ConfigError


def text_response(text: str | None, finish: str = "STOP") -> types.GenerateContentResponse:
    parts = [types.Part(text=text)] if text is not None else None
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish)
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=5
        ),
    )


def grounded_response() -> types.GenerateContentResponse:
    response = text_response("Inground pools in Texas cost $45,000 to $85,000.")
    response.candidates[0].grounding_metadata = types.GroundingMetadata(
        web_search_queries=["inground pool cost texas", "fiberglass vs concrete pool cost"],
        grounding_chunks=[
            types.GroundingChunk(
                web=types.GroundingChunkWeb(uri="https://redirect/1", title="a.com", domain="a.com")
            ),
            types.GroundingChunk(),  # a non-web chunk, which must be skipped
            types.GroundingChunk(
                web=types.GroundingChunkWeb(uri="https://redirect/2", title="b.org")
            ),
        ],
        grounding_supports=[
            types.GroundingSupport(
                segment=types.Segment(start_index=0, end_index=48, text="Inground pools ..."),
                grounding_chunk_indices=[0, 1, 2],
            )
        ],
    )
    return response


def fake_vector(text: str, dims: int) -> list[float]:
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return (
        np.random.default_rng(seed).normal(size=dims) * 3
    ).tolist()  # deliberately not unit length


def api_error(cls: type[errors.APIError], code: int, message: str) -> errors.APIError:
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


class FakeModels:
    def __init__(self) -> None:
        self.responses: list[Any] = []  # queued responses or exceptions for generate_content
        self.embed_errors: list[Exception] = []
        self.generate_calls: list[dict[str, Any]] = []
        self.embed_calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.generate_calls.append({"model": model, "contents": contents, "config": config})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def embed_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.embed_calls.append({"model": model, "contents": contents, "config": config})
        if self.embed_errors:
            raise self.embed_errors.pop(0)
        dims = config.output_dimensionality
        return types.EmbedContentResponse(
            embeddings=[
                types.ContentEmbedding(values=fake_vector(c.parts[0].text, dims)) for c in contents
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def gemini(client, tmp_path) -> Gemini:
    return Gemini(
        client,
        model="gemini-test",
        embedding_model="gemini-embedding-2",
        dimensions=8,
        cache=Cache(tmp_path / ".cache"),
        batch_size=100,
        retry_wait=wait_none(),
    )


class Queries(BaseModel):
    queries: list[str]


# --- generate ---------------------------------------------------------------------------


def test_generate_returns_text_and_counts_usage(gemini, client):
    client.models.responses.append(text_response("Pool Cost Guide"))
    assert gemini.generate("title?", system="be brief") == "Pool Cost Guide"
    call = client.models.generate_calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].system_instruction == "be brief"
    assert (gemini.usage.requests, gemini.usage.prompt_tokens, gemini.usage.output_tokens) == (
        1,
        10,
        5,
    )


def test_generate_is_cached(gemini, client):
    client.models.responses.append(text_response("once"))
    assert gemini.generate("same prompt") == "once"
    assert gemini.generate("same prompt") == "once"
    assert len(client.models.generate_calls) == 1
    assert gemini.usage.cached == 1


def test_changing_model_or_prompt_misses_cache(gemini, client):
    client.models.responses += [text_response("a"), text_response("b"), text_response("c")]
    gemini.generate("p1")
    gemini.generate("p2")
    gemini.model = "gemini-other"
    gemini.generate("p1")
    assert len(client.models.generate_calls) == 3


def test_blocked_response_raises(gemini, client):
    client.models.responses.append(text_response(None, finish="SAFETY"))
    with pytest.raises(GeminiError, match="SAFETY"):
        gemini.generate("x")


# --- generate_json ----------------------------------------------------------------------


def test_generate_json_validates_and_sends_schema(gemini, client):
    client.models.responses.append(text_response('{"queries": ["pool cost", "pool size"]}'))
    result = gemini.generate_json("list queries", Queries)
    assert result == Queries(queries=["pool cost", "pool size"])
    config = client.models.generate_calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == Queries.model_json_schema()


def test_generate_json_cached_result_is_validated_object(gemini, client):
    client.models.responses.append(text_response('{"queries": ["a"]}'))
    gemini.generate_json("p", Queries)
    assert gemini.generate_json("p", Queries) == Queries(queries=["a"])
    assert len(client.models.generate_calls) == 1


@pytest.mark.parametrize("bad", ["not json", '{"queries": "should be a list"}'])
def test_generate_json_rejects_bad_output_and_does_not_cache_it(gemini, client, bad):
    client.models.responses += [text_response(bad), text_response('{"queries": ["ok"]}')]
    with pytest.raises(GeminiError, match="didn't match Queries"):
        gemini.generate_json("p", Queries)
    assert gemini.generate_json("p", Queries) == Queries(queries=["ok"])


# --- ground -----------------------------------------------------------------------------


def test_ground_returns_searches_sources_and_citations(gemini, client):
    client.models.responses.append(grounded_response())
    answer = gemini.ground("inground pool cost texas")

    assert answer.search_queries == ("inground pool cost texas", "fiberglass vs concrete pool cost")
    assert [s.domain for s in answer.sources] == ["a.com", "b.org"]  # non-web chunk skipped
    assert answer.citations[0].source_indices == (0, 1)  # chunk 2 remapped to source 1
    assert gemini.usage.searches == 2
    tools = client.models.generate_calls[0]["config"].tools
    assert tools[0].google_search is not None


def test_ground_round_trips_through_cache(gemini, client):
    client.models.responses.append(grounded_response())
    first = gemini.ground("q")
    second = gemini.ground("q")
    assert isinstance(second, GroundedAnswer)
    assert first == second
    assert len(client.models.generate_calls) == 1


def test_ground_without_search_returns_empty_metadata(gemini, client):
    client.models.responses.append(text_response("2 + 2 = 4"))
    answer = gemini.ground("2+2")
    assert answer.text == "2 + 2 = 4"
    assert answer.search_queries == () and answer.sources == ()


def test_ground_refuses_when_turned_off(gemini):
    gemini.grounding = False
    with pytest.raises(GeminiError, match="GEMINI_GROUNDING"):
        gemini.ground("q")


# --- embed ------------------------------------------------------------------------------


def test_embed_shape_and_unit_length(gemini):
    vectors = gemini.embed(["pool cost", "pool size", "pool heater"], task="clustering")
    assert vectors.shape == (3, 8)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, rtol=1e-5)


def test_embed_sends_one_content_per_text_with_prefixes(gemini, client):
    gemini.embed(["pool cost"], task="query")
    gemini.embed(
        ["Fiberglass pools cost less.", "No title here."], task="document", titles=["Cost", None]
    )
    texts = [c.parts[0].text for call in client.models.embed_calls for c in call["contents"]]
    assert texts == [
        "task: search result | query: pool cost",
        "title: Cost | text: Fiberglass pools cost less.",
        "title: none | text: No title here.",
    ]
    assert all(isinstance(c, types.Content) for c in client.models.embed_calls[1]["contents"])
    config = client.models.embed_calls[0]["config"]
    assert config.task_type is None
    assert config.output_dimensionality == 8


def test_embedding_001_uses_task_type(gemini, client):
    gemini.embedding_model = "gemini-embedding-001"
    gemini.embed(["pool cost"], task="query")
    call = client.models.embed_calls[0]
    assert call["config"].task_type == "RETRIEVAL_QUERY"
    assert call["contents"][0].parts[0].text == "pool cost"


def test_embed_batches(gemini, client):
    gemini.batch_size = 100
    gemini.embed([f"query {i}" for i in range(250)])
    assert [len(call["contents"]) for call in client.models.embed_calls] == [100, 100, 50]
    assert gemini.usage.embedded_texts == 250


def test_embed_uses_cache_and_keeps_order(gemini, client):
    first = gemini.embed(["a", "b"])
    both = gemini.embed(["c", "b", "a"])
    sent = [c.parts[0].text for c in client.models.embed_calls[1]["contents"]]
    assert sent == ["task: sentence similarity | query: c"]  # only the new text
    np.testing.assert_allclose(both[1], first[1], rtol=1e-6)
    np.testing.assert_allclose(both[2], first[0], rtol=1e-6)


def test_embed_duplicates_sent_once(gemini, client):
    vectors = gemini.embed(["same", "same", "other"])
    assert len(client.models.embed_calls[0]["contents"]) == 2
    np.testing.assert_allclose(vectors[0], vectors[1])


def test_same_text_different_task_is_a_different_embedding(gemini, client):
    gemini.embed(["pool cost"], task="query")
    gemini.embed(["pool cost"], task="clustering")
    assert len(client.models.embed_calls) == 2


def test_embed_empty_list(gemini, client):
    assert gemini.embed([]).shape == (0, 8)
    assert client.models.embed_calls == []


def test_embed_rejects_blank_text(gemini):
    with pytest.raises(ValueError, match="Text 1 is empty"):
        gemini.embed(["ok", "  "])


def test_titles_only_for_documents(gemini):
    with pytest.raises(ValueError, match="titles"):
        gemini.embed(["a"], task="query", titles=["t"])


# --- errors and retries -----------------------------------------------------------------


def test_retries_overload_then_succeeds(gemini, client):
    client.models.responses += [
        api_error(errors.ServerError, 503, "overloaded"),
        api_error(errors.ClientError, 429, "slow down"),
        text_response("ok"),
    ]
    assert gemini.generate("x") == "ok"
    assert len(client.models.generate_calls) == 3


def test_gives_up_after_max_attempts(gemini, client):
    client.models.embed_errors = [api_error(errors.ServerError, 500, "boom")] * 5
    with pytest.raises(GeminiError, match="500"):
        gemini.embed(["x"])
    assert len(client.models.embed_calls) == 5


@pytest.mark.parametrize(
    ("code", "hint"),
    [(403, "GEMINI_API_KEY"), (400, "GEMINI_API_KEY"), (404, "GEMINI_MODEL")],
)
def test_client_errors_explain_what_to_check(gemini, client, code, hint):
    message = "API key not valid" if code == 400 else "nope"
    client.models.responses.append(api_error(errors.ClientError, code, message))
    with pytest.raises(GeminiError, match=hint):
        gemini.generate("x")
    assert len(client.models.generate_calls) == 1  # not retried


def test_from_settings_needs_a_key(settings):
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        Gemini.from_settings(settings)


def test_from_settings_reads_models(project):
    from seo_toolkit.core.config import Settings

    settings = Settings(
        _env_file=None,
        project_dir=project,
        gemini_api_key="test-key",
        gemini_model="gemini-x",
        gemini_embedding_dimensions=1536,
    )
    gemini = Gemini.from_settings(settings)
    assert (gemini.model, gemini.embedding_model, gemini.dimensions) == (
        "gemini-x",
        "gemini-embedding-2",
        1536,
    )
    assert gemini.cache is not None and gemini.cache.directory == project / ".cache"
