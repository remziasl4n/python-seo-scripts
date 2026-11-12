"""Gemini: text and structured generation, Google Search grounding, and embeddings.

    gemini = Gemini.from_settings()

    gemini.generate("Write a title for ...")                    # str
    gemini.generate_json(prompt, schema=FanoutQueries)           # a validated FanoutQueries
    answer = gemini.ground("how much does an inground pool cost in texas")
    answer.search_queries    # the Google searches Gemini ran: real fan-out evidence
    answer.sources           # the pages it drew on
    gemini.embed(["pool cost", "pool price"], task="query")      # one unit-length row per text

Every call goes through the disk cache, so rerunning a tool costs nothing. Model
names come from .env (GEMINI_MODEL, GEMINI_EMBEDDING_MODEL) because they change often.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypeVar

import numpy as np
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from seo_toolkit.core.cache import Cache
from seo_toolkit.core.config import Settings, get_settings
from seo_toolkit.core.errors import ToolkitError

T = TypeVar("T", bound=BaseModel)

# What an embedding is for. Queries and documents are embedded differently so that
# query-to-passage similarity works as retrieval (see docs/semantic-seo-principles.md §3.8).
EmbedTask = Literal[
    "query", "document", "question", "fact_check", "clustering", "similarity", "classification"
]

# gemini-embedding-2 and later take the task as a prefix on the text
_PREFIXES: dict[str, str] = {
    "query": "task: search result | query: {text}",
    "question": "task: question answering | query: {text}",
    "fact_check": "task: fact checking | query: {text}",
    "clustering": "task: clustering | query: {text}",
    "similarity": "task: sentence similarity | query: {text}",
    "classification": "task: classification | query: {text}",
    "document": "title: {title} | text: {text}",
}

# gemini-embedding-001 takes it as a task_type setting instead
_TASK_TYPES: dict[str, str] = {
    "query": "RETRIEVAL_QUERY",
    "question": "QUESTION_ANSWERING",
    "fact_check": "FACT_VERIFICATION",
    "clustering": "CLUSTERING",
    "similarity": "SEMANTIC_SIMILARITY",
    "classification": "CLASSIFICATION",
    "document": "RETRIEVAL_DOCUMENT",
}


def _uses_task_type(model: str) -> bool:
    return "embedding-001" in model or model.startswith("text-embedding")


class GeminiError(ToolkitError):
    """A Gemini call failed. The message says what to check."""


@dataclass(frozen=True)
class Source:
    """A page a grounded answer drew on."""

    title: str
    url: str  # Google's redirect link to the page
    domain: str


@dataclass(frozen=True)
class Citation:
    """A span of the answer and the sources (indexes into `sources`) that support it."""

    text: str
    start: int
    end: int
    source_indices: tuple[int, ...]


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    search_queries: tuple[str, ...]
    sources: tuple[Source, ...]
    citations: tuple[Citation, ...]
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundedAnswer:
        return cls(
            text=data["text"],
            search_queries=tuple(data["search_queries"]),
            sources=tuple(Source(**s) for s in data["sources"]),
            citations=tuple(
                Citation(c["text"], c["start"], c["end"], tuple(c["source_indices"]))
                for c in data["citations"]
            ),
            model=data["model"],
        )


@dataclass
class Usage:
    """What this session has spent, for reporting at the end of a run."""

    requests: int = 0
    cached: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0  # grounded searches are billed per query on Gemini 3+
    embedded_texts: int = 0


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, errors.ServerError):
        return True
    return isinstance(error, errors.ClientError) and error.code == 429


def _explain(error: errors.APIError) -> str:
    code, message = error.code, error.message or str(error)
    if code in (401, 403) or (code == 400 and "api key" in message.lower()):
        return (
            f"Gemini rejected the request ({code}): {message}\n"
            "Check GEMINI_API_KEY in .env (keys: https://aistudio.google.com/apikey)."
        )
    if code == 404:
        return (
            f"Gemini model not found ({code}): {message}\n"
            "Check GEMINI_MODEL / GEMINI_EMBEDDING_MODEL in .env against "
            "https://aistudio.google.com/docs/models."
        )
    if code == 429:
        return f"Gemini rate limit or quota reached, even after retrying: {message}"
    return f"Gemini API error ({code}): {message}"


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return vectors / norms


class Gemini:
    def __init__(
        self,
        client: Any,
        model: str,
        embedding_model: str,
        dimensions: int = 768,
        grounding: bool = True,
        cache: Cache | None = None,
        batch_size: int = 100,
        max_attempts: int = 5,
        retry_wait: wait_base | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self.grounding = grounding
        self.cache = cache
        self.batch_size = batch_size
        self.usage = Usage()
        self._retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max_attempts),
            wait=retry_wait or wait_exponential(multiplier=2, max=60),
            reraise=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None, refresh: bool = False) -> Gemini:
        settings = settings or get_settings()
        client = genai.Client(api_key=settings.require("gemini_api_key"))
        return cls(
            client,
            model=settings.gemini_model,
            embedding_model=settings.gemini_embedding_model,
            dimensions=settings.gemini_embedding_dimensions,
            grounding=settings.gemini_grounding,
            cache=Cache.from_settings(settings, refresh=refresh),
        )

    # --- Plumbing -------------------------------------------------------------------

    def _call(self, fn: Callable[..., Any], **kwargs: Any) -> Any:
        """Call the API, retrying on overload and rate limits, with readable errors."""
        try:
            response = self._retrying(fn, **kwargs)
        except errors.APIError as e:
            raise GeminiError(_explain(e)) from e
        self.usage.requests += 1
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.usage.prompt_tokens += usage.prompt_token_count or 0
            self.usage.output_tokens += usage.candidates_token_count or 0
        return response

    def _cached(self, namespace: str, key: dict[str, Any], compute: Callable[[], Any]) -> Any:
        if self.cache is None:
            return compute()
        value = self.cache.get(namespace, key)
        if value is not None:
            self.usage.cached += 1
            return value
        value = compute()
        self.cache.set(namespace, key, value)
        return value

    @staticmethod
    def _text(response: types.GenerateContentResponse) -> str:
        text = response.text
        if text:
            return text
        if response.candidates:
            reason: object = response.candidates[0].finish_reason
        elif response.prompt_feedback:
            reason = response.prompt_feedback.block_reason
        else:
            reason = "unknown"
        raise GeminiError(f"Gemini returned no text (reason: {reason}).")

    # --- Generation -----------------------------------------------------------------

    def generate(
        self, prompt: str, *, system: str | None = None, temperature: float | None = None
    ) -> str:
        """Plain text from the model."""
        key = {"model": self.model, "prompt": prompt, "system": system, "temperature": temperature}

        def call() -> str:
            response = self._call(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system, temperature=temperature
                ),
            )
            return self._text(response)

        return str(self._cached("gemini.generate", key, call))

    def generate_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """Structured output, validated against a pydantic model."""
        schema_json = schema.model_json_schema()
        key = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "schema": schema_json,
        }

        def call() -> Any:
            response = self._call(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_json_schema=schema_json,
                ),
            )
            text = self._text(response)
            try:
                data = json.loads(text)
                schema.model_validate(data)  # check before caching, so bad output isn't kept
            except (json.JSONDecodeError, ValidationError) as e:
                raise GeminiError(
                    f"Gemini's answer didn't match {schema.__name__}: {e}\nAnswer: {text[:300]}"
                ) from e
            return data

        return schema.model_validate(self._cached("gemini.json", key, call))

    def ground(self, prompt: str, *, system: str | None = None) -> GroundedAnswer:
        """An answer grounded in Google Search, with the searches it ran and its sources."""
        if not self.grounding:
            raise GeminiError(
                "Grounding with Google Search is turned off. "
                "Set GEMINI_GROUNDING=true in .env to use this."
            )
        key = {"model": self.model, "prompt": prompt, "system": system}

        def call() -> dict[str, Any]:
            response = self._call(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            answer = self._parse_grounded(response)
            self.usage.searches += len(answer.search_queries)
            return answer.to_dict()

        return GroundedAnswer.from_dict(self._cached("gemini.ground", key, call))

    def _parse_grounded(self, response: types.GenerateContentResponse) -> GroundedAnswer:
        text = self._text(response)
        candidate = response.candidates[0] if response.candidates else None
        meta = candidate.grounding_metadata if candidate else None
        if meta is None:  # the model answered without searching
            return GroundedAnswer(text, (), (), (), self.model)

        sources: list[Source] = []
        index_map: dict[int, int] = {}  # chunk index -> index in `sources`
        for i, chunk in enumerate(meta.grounding_chunks or []):
            if chunk.web is None:
                continue
            index_map[i] = len(sources)
            web = chunk.web
            sources.append(Source(web.title or "", web.uri or "", web.domain or web.title or ""))

        citations = []
        for support in meta.grounding_supports or []:
            segment = support.segment
            if segment is None:
                continue
            indices = tuple(
                index_map[i] for i in support.grounding_chunk_indices or [] if i in index_map
            )
            citations.append(
                Citation(
                    segment.text or "", segment.start_index or 0, segment.end_index or 0, indices
                )
            )

        return GroundedAnswer(
            text=text,
            search_queries=tuple(meta.web_search_queries or []),
            sources=tuple(sources),
            citations=tuple(citations),
            model=self.model,
        )

    # --- Embeddings -----------------------------------------------------------------

    def _prepare(self, text: str, task: EmbedTask, title: str | None) -> str:
        if _uses_task_type(self.embedding_model):
            return f"{title}\n\n{text}" if title else text
        return _PREFIXES[task].format(text=text, title=title or "none")

    def embed(
        self,
        texts: Sequence[str],
        task: EmbedTask = "similarity",
        titles: Sequence[str | None] | None = None,
    ) -> np.ndarray:
        """Embed texts as an array of shape (len(texts), dimensions), each row unit length.

        Use task="query" for search queries and task="document" (optionally with titles)
        for passages you want to match against them. Inputs over the model's token limit
        (8,192 for gemini-embedding-2) are silently cut, so embed passages, not whole pages.
        """
        if titles is not None and (task != "document" or len(titles) != len(texts)):
            raise ValueError("titles only apply to task='document', one per text.")
        for i, text in enumerate(texts):
            if not text.strip():
                raise ValueError(f"Text {i} is empty; remove blank rows before embedding.")

        prepared = [
            self._prepare(t, task, titles[i] if titles else None) for i, t in enumerate(texts)
        ]
        vectors: list[list[float] | None] = [None] * len(prepared)

        def key(text: str) -> dict[str, Any]:
            return {
                "model": self.embedding_model,
                "dimensions": self.dimensions,
                "task": task,
                "text": text,
            }

        missing: dict[str, list[int]] = {}  # each distinct text is embedded once
        for i, text in enumerate(prepared):
            stored = self.cache.get("gemini.embed", key(text)) if self.cache else None
            if stored is not None:
                vectors[i] = stored
                self.usage.cached += 1
            else:
                missing.setdefault(text, []).append(i)

        pending = list(missing)
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            for text, values in zip(batch, self._embed_batch(batch, task), strict=True):
                for i in missing[text]:
                    vectors[i] = values
                if self.cache:
                    self.cache.set("gemini.embed", key(text), values)

        if not vectors:
            return np.empty((0, self.dimensions), dtype=np.float32)
        return _normalize(np.array(vectors, dtype=np.float32))

    def _embed_batch(self, texts: list[str], task: EmbedTask) -> list[list[float]]:
        task_type = _TASK_TYPES[task] if _uses_task_type(self.embedding_model) else None
        # One Content per text: a plain list would be merged into a single embedding
        contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in texts]
        response = self._call(
            self.client.models.embed_content,
            model=self.embedding_model,
            contents=contents,
            config=types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=self.dimensions
            ),
        )
        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            raise GeminiError(f"Asked for {len(texts)} embeddings but got {len(embeddings)}.")
        self.usage.embedded_texts += len(texts)
        return [list(e.values or []) for e in embeddings]
