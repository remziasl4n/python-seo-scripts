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

import httpx
import numpy as np
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
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


Purpose = Literal["text", "grounding", "embeddings"]
# The .env setting that picks the model for each kind of call
_MODEL_SETTING: dict[str, str] = {
    "text": "GEMINI_MODEL",
    "grounding": "GEMINI_GROUNDING_MODEL",
    "embeddings": "GEMINI_EMBEDDING_MODEL",
}
FALLBACK_MODEL = "gemini-2.5-flash"


def _retry_delay(error: errors.APIError) -> float | None:
    """Seconds Google asks us to wait (its RetryInfo), or None if it gave no delay.

    A 429 with a delay is a short rate limit worth waiting out. A 429 without one is a
    quota the plan doesn't have, and retrying can't fix it.
    """
    body = error.details if isinstance(error.details, dict) else {}
    for detail in body.get("error", {}).get("details", None) or []:
        if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(detail.get("retryDelay", "0s")).rstrip("s"))
            except ValueError:
                return 0.0
    return None


PER_MINUTE_WAIT = 62.0  # a per-minute quota frees up when the next minute starts


def _per_minute_quota(error: errors.APIError) -> bool:
    """True for "N requests per minute" limits (e.g. 100 embeddings a minute on the free
    plan). Google's suggested delay for these can be a few milliseconds, which is too
    short: the quota only frees up when the minute rolls over."""
    body = error.details if isinstance(error.details, dict) else {}
    for detail in body.get("error", {}).get("details", None) or []:
        if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("QuotaFailure"):
            for violation in detail.get("violations", []) or []:
                if "PerMinute" in str(violation.get("quotaId", "")):
                    return True
    return False


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, (errors.ServerError, httpx.TimeoutException)):
        return True
    return (
        isinstance(error, errors.ClientError)
        and error.code == 429
        and (_retry_delay(error) is not None or _per_minute_quota(error))
    )


def _wait_with(backoff: wait_base) -> Callable[[RetryCallState], float]:
    """Wait out per-minute quotas; otherwise as long as Google asks, or back off."""

    def wait(state: RetryCallState) -> float:
        error = state.outcome.exception() if state.outcome else None
        if isinstance(error, errors.APIError):
            if _per_minute_quota(error):
                return PER_MINUTE_WAIT
            delay = _retry_delay(error)
            if delay is not None:
                return min(max(delay, 1.0), 60.0)
        return backoff(state)

    return wait


def _explain(error: errors.APIError, model: str, purpose: Purpose) -> str:
    code, message = error.code, (error.message or str(error)).strip()
    setting = _MODEL_SETTING[purpose]
    if code in (401, 403) or (code == 400 and "api key" in message.lower()):
        return (
            f"Gemini rejected the request ({code}): {message}\n"
            "Check GEMINI_API_KEY in .env (keys: https://aistudio.google.com/apikey)."
        )
    if code == 404:
        return (
            f"Gemini model {model} not found ({code}).\n"
            f"Check {setting} in .env against https://aistudio.google.com/docs/models."
        )
    if code == 429 and _per_minute_quota(error):
        return (
            f"Gemini's per-minute limit for {purpose} on {model} kept being hit, even after "
            "waiting (429). The free plan allows about 100 embeddings a minute: try a shorter "
            "list, run it again (finished parts are cached), or enable billing."
        )
    if code == 429 and _retry_delay(error) is None:
        advice = (
            "Grounding on Gemini 3 models needs a paid plan. "
            f"Set GEMINI_GROUNDING_MODEL={FALLBACK_MODEL} in .env, or enable billing at "
            "https://aistudio.google.com."
            if purpose == "grounding"
            else "Check usage at https://ai.dev/rate-limit, wait for the daily reset, "
            f"switch {setting} to another model, or enable billing."
        )
        return f"Your Gemini plan has no quota for {purpose} on {model} (429).\n{advice}"
    if code == 429:
        return f"Gemini rate limit on {model} (429), even after waiting and retrying: {message}"
    if code in (500, 502, 503, 504):
        return (
            f"Gemini model {model} is overloaded right now ({code}).\n"
            f"Try again in a few minutes, or set {setting} in .env to another model, "
            f"e.g. {FALLBACK_MODEL}."
        )
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
        grounding_model: str | None = None,
        cache: Cache | None = None,
        batch_size: int = 100,
        max_attempts: int = 5,
        retry_wait: wait_base | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """`grounding_model` defaults to `model`. `timeout_seconds` is only used in messages."""
        self.client = client
        self.model = model
        self.grounding_model = grounding_model or model
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self.grounding = grounding
        self.cache = cache
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.usage = Usage()
        # Told how long a retry will wait (e.g. for a per-minute quota), so a tool can show it
        self.on_wait: Callable[[float], None] | None = None
        self._retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max_attempts),
            wait=retry_wait or _wait_with(wait_exponential(multiplier=2, max=60)),
            before_sleep=self._before_sleep,
            reraise=True,
        )

    def _before_sleep(self, state: RetryCallState) -> None:
        if self.on_wait and state.next_action is not None:
            self.on_wait(state.next_action.sleep)

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        refresh: bool = False,
        max_attempts: int = 5,
        timeout_seconds: float | None = None,
    ) -> Gemini:
        """`timeout_seconds` overrides GEMINI_TIMEOUT_SECONDS for every request."""
        settings = settings or get_settings()
        timeout = timeout_seconds or settings.gemini_timeout_seconds
        client = genai.Client(
            api_key=settings.require("gemini_api_key"),
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
        return cls(
            client,
            model=settings.gemini_model,
            grounding_model=settings.gemini_grounding_model,
            embedding_model=settings.gemini_embedding_model,
            dimensions=settings.gemini_embedding_dimensions,
            grounding=settings.gemini_grounding,
            cache=Cache.from_settings(settings, refresh=refresh),
            max_attempts=max_attempts,
            timeout_seconds=timeout,
        )

    # --- Plumbing -------------------------------------------------------------------

    def _call(self, fn: Callable[..., Any], purpose: Purpose, **kwargs: Any) -> Any:
        """Call the API, retrying on overload and short rate limits, with readable errors."""
        model = str(kwargs.get("model", ""))
        try:
            response = self._retrying(fn, **kwargs)
        except errors.APIError as e:
            raise GeminiError(_explain(e, model, purpose)) from e
        except httpx.TimeoutException as e:
            limit = f" within {self.timeout_seconds:g}s" if self.timeout_seconds else ""
            raise GeminiError(
                f"Gemini model {model} didn't answer{limit}. It may be "
                f"overloaded: try again, or set {_MODEL_SETTING[purpose]} to another model "
                f"(e.g. {FALLBACK_MODEL}) or raise GEMINI_TIMEOUT_SECONDS."
            ) from e
        except httpx.HTTPError as e:
            raise GeminiError(f"Couldn't reach the Gemini API: {e}") from e
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
                "text",
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
                "text",
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
        key = {"model": self.grounding_model, "prompt": prompt, "system": system}

        def call() -> dict[str, Any]:
            response = self._call(
                self.client.models.generate_content,
                "grounding",
                model=self.grounding_model,
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
            return GroundedAnswer(text, (), (), (), self.grounding_model)

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
            model=self.grounding_model,
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
        progress: Callable[[int, int], None] | None = None,
    ) -> np.ndarray:
        """Embed texts as an array of shape (len(texts), dimensions), each row unit length.

        Use task="query" for search queries and task="document" (optionally with titles)
        for passages you want to match against them. Inputs over the model's token limit
        (8,192 for gemini-embedding-2) are silently cut, so embed passages, not whole pages.
        `progress(done, total)` is called after each batch sent to Gemini.
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
            if progress:
                progress(min(start + self.batch_size, len(pending)), len(pending))

        if not vectors:
            return np.empty((0, self.dimensions), dtype=np.float32)
        return _normalize(np.array(vectors, dtype=np.float32))

    def _embed_batch(self, texts: list[str], task: EmbedTask) -> list[list[float]]:
        task_type = _TASK_TYPES[task] if _uses_task_type(self.embedding_model) else None
        # One Content per text: a plain list would be merged into a single embedding
        contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in texts]
        response = self._call(
            self.client.models.embed_content,
            "embeddings",
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
