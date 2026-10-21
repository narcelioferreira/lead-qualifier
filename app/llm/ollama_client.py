"""Cliente do Ollama (SLM local) com structured output via `format` = JSON Schema."""

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, HttpUrl
from tenacity.wait import wait_base

from app.llm.base import (
    DEFAULT_TIMEOUT,
    LLMOutputError,
    LLMResult,
    Message,
    check_chat,
    parse_output,
    send_with_retry,
    strict_json_schema,
)
from app.routing.cost import ModelSpec, Usage, cost_usd

PROVIDER = "ollama"


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
