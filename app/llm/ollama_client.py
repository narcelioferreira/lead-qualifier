"""Cliente do Ollama: SLM local com structured output (`format` = JSON Schema) e embeddings."""

import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, HttpUrl
from tenacity.wait import wait_base

from app.llm.base import (
    DEFAULT_TIMEOUT,
    LLMOutputError,
    LLMRequestError,
    LLMResult,
    Message,
    check_chat,
    parse_output,
    send_with_retry,
    strict_json_schema,
)
from app.routing.cost import ModelSpec, Usage, cost_usd

PROVIDER = "ollama"
# Limite por chamada de embeddings: a ingestão manda os chunks em lotes.
MAX_EMBED_INPUTS = 64


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    usage: Usage
    model_key: str
    model: str
    latency_ms: float


class OllamaClient:
    def __init__(
        self,
        base_url: HttpUrl | str,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
        retry_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        # A URL vem da configuração (OLLAMA_BASE_URL), nunca do lead.
        self._base_url = str(base_url).rstrip("/")
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._retry_sleep = retry_sleep

    def __repr__(self) -> str:
        return f"OllamaClient(base_url={self._base_url!r})"

    async def structured[T: BaseModel](
        self,
        spec: ModelSpec,
        messages: Sequence[Message],
        schema: type[T],
    ) -> LLMResult[T]:
        check_chat(spec, PROVIDER)
        options: dict[str, Any] = {"temperature": spec.temperature or 0}
        if spec.max_output_tokens:
            options["num_predict"] = spec.max_output_tokens
        body = {
            "model": spec.model,
            "messages": [m.model_dump() for m in messages],
            "format": strict_json_schema(schema),
            "stream": False,
            "options": options,
        }
        if spec.think is not None:
            body["think"] = spec.think
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response, attempts = await send_with_retry(
                lambda: client.post(f"{self._base_url}/api/chat", json=body),
                PROVIDER,
                self._retry_wait,
                self._retry_sleep,
            )
        latency_ms = (time.perf_counter() - start) * 1000

        data = response.json()
        if data.get("done_reason") == "length":
            raise LLMOutputError(f"{PROVIDER}: resposta incompleta (limite de tokens)")
        text = str((data.get("message") or {}).get("content") or "")
        usage = Usage(
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
        return LLMResult(
            parsed=parse_output(text, schema, PROVIDER),
            usage=usage,
            model_key=spec.key,
            model=str(data.get("model") or spec.model),
            latency_ms=latency_ms,
            cost_usd=cost_usd(usage, spec),
            attempts=attempts,
        )

    async def embed(self, spec: ModelSpec, texts: Sequence[str]) -> Embeddings:
        """Um vetor por texto, na mesma ordem. A resposta é validada: quantidade, dimensão
        igual entre os vetores e só números finitos (um vetor ruim no pgvector estragaria a
        busca em silêncio)."""
        if spec.provider != PROVIDER or spec.kind != "embedding":
            raise LLMRequestError(f"{spec.key} não é um modelo de embeddings do {PROVIDER}")
        if not 1 <= len(texts) <= MAX_EMBED_INPUTS:
            raise LLMRequestError(f"embeddings: de 1 a {MAX_EMBED_INPUTS} textos por chamada")
        body = {"model": spec.model, "input": list(texts), "truncate": True}
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response, _ = await send_with_retry(
                lambda: client.post(f"{self._base_url}/api/embed", json=body),
                PROVIDER,
                self._retry_wait,
                self._retry_sleep,
            )
        latency_ms = (time.perf_counter() - start) * 1000

        data = response.json()
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise LLMOutputError(f"{PROVIDER}: quantidade de embeddings diferente da pedida")
        dims = {len(v) if isinstance(v, list) else -1 for v in vectors}
        if len(dims) != 1 or dims == {-1} or dims == {0}:
            raise LLMOutputError(f"{PROVIDER}: embeddings com dimensões inválidas")
        if not all(
            isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)
            for v in vectors
            for x in v
        ):
            raise LLMOutputError(f"{PROVIDER}: embeddings com valores não numéricos")
        return Embeddings(
            vectors=[[float(x) for x in v] for v in vectors],
            usage=Usage(input_tokens=data.get("prompt_eval_count", 0)),
            model_key=spec.key,
            model=str(data.get("model") or spec.model),
            latency_ms=latency_ms,
        )
