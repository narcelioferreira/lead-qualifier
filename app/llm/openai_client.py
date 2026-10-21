"""Cliente da OpenAI (Responses API) com structured output estrito.

Usa HTTP direto (httpx) em vez do SDK para controlar retry, timeout e o que entra nas mensagens
de erro. A Responses API é a recomendada pela OpenAI para modelos de raciocínio.
"""

import time
from collections.abc import Sequence
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

OPENAI_BASE_URL = "https://api.openai.com/v1"
PROVIDER = "openai"


class OpenAIClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = OPENAI_BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_wait = retry_wait

    def __repr__(self) -> str:
        return f"OpenAIClient(base_url={self._base_url!r})"

    async def structured[T: BaseModel](
        self,
        spec: ModelSpec,
        messages: Sequence[Message],
        schema: type[T],
    ) -> LLMResult[T]:
        check_chat(spec, PROVIDER)
        body: dict[str, Any] = {
            "model": spec.model,
            "input": [m.model_dump() for m in messages],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": strict_json_schema(schema),
                    "strict": True,
                }
            },
            # Não guarda a conversa na OpenAI: o lead tem dados de contato.
            "store": False,
        }
        if spec.reasoning_effort:
            body["reasoning"] = {"effort": spec.reasoning_effort}
        if spec.max_output_tokens:
            body["max_output_tokens"] = spec.max_output_tokens

        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            response, attempts = await send_with_retry(
                lambda: client.post(f"{self._base_url}/responses", json=body),
                PROVIDER,
                self._retry_wait,
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
    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason", "desconhecido")
        raise LLMOutputError(f"{PROVIDER}: resposta incompleta ({reason})")
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue  # ex.: itens de raciocínio
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise LLMOutputError(f"{PROVIDER}: o modelo recusou a tarefa")
            if content.get("type") == "output_text":
                return str(content.get("text") or "")
    raise LLMOutputError(f"{PROVIDER}: resposta sem texto de saída")


def _usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=raw.get("input_tokens", 0),
        cached_input_tokens=(raw.get("input_tokens_details") or {}).get("cached_tokens", 0),
        output_tokens=raw.get("output_tokens", 0),
        reasoning_tokens=(raw.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
    )
