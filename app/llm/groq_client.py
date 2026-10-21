"""Cliente da Groq (Chat Completions compatível com OpenAI) com structured output estrito.

Usa HTTP direto (httpx) para controlar retry, timeout e o que entra nas mensagens de erro.
Só os modelos com `strict: true` garantem saída no schema (ver `models.yaml`).
"""

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr
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

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
PROVIDER = "groq"


class GroqClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = GROQ_BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
        retry_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._retry_sleep = retry_sleep

    def __repr__(self) -> str:
        return f"GroqClient(base_url={self._base_url!r})"

    async def structured[T: BaseModel](
        self,
        spec: ModelSpec,
        messages: Sequence[Message],
        schema: type[T],
    ) -> LLMResult[T]:
        check_chat(spec, PROVIDER)
        body: dict[str, Any] = {
            "model": spec.model,
            "messages": [m.model_dump() for m in messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": strict_json_schema(schema),
                    "strict": True,
                },
            },
            # O raciocínio do modelo não é devolvido nem guardado: só a saída estruturada.
            "include_reasoning": False,
        }
        if spec.reasoning_effort:
            body["reasoning_effort"] = spec.reasoning_effort
        if spec.temperature is not None:
            body["temperature"] = spec.temperature
        if spec.max_output_tokens:
            body["max_completion_tokens"] = spec.max_output_tokens

        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            response, attempts = await send_with_retry(
                lambda: client.post(f"{self._base_url}/chat/completions", json=body),
                PROVIDER,
                self._retry_wait,
                self._retry_sleep,
            )
        latency_ms = (time.perf_counter() - start) * 1000

        data = response.json()
        usage = _usage(data.get("usage") or {})
        return LLMResult(
            parsed=parse_output(_output_text(data), schema, PROVIDER),
            usage=usage,
            model_key=spec.key,
            model=str(data.get("model") or spec.model),
            latency_ms=latency_ms,
            cost_usd=cost_usd(usage, spec),
            attempts=attempts,
        )


def _output_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise LLMOutputError(f"{PROVIDER}: resposta sem texto de saída")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise LLMOutputError(f"{PROVIDER}: resposta incompleta (limite de tokens)")
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise LLMOutputError(f"{PROVIDER}: o modelo recusou a tarefa")
    text = message.get("content")
    if not text:
        raise LLMOutputError(f"{PROVIDER}: resposta sem texto de saída")
    return str(text)


def _usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=raw.get("prompt_tokens", 0),
        cached_input_tokens=(raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        output_tokens=raw.get("completion_tokens", 0),
        reasoning_tokens=(raw.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
    )
