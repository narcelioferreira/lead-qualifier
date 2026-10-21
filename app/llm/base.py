"""Tipos comuns aos clientes de LLM: mensagens, resultado, erros, retry e schema estrito.

Os clientes só devolvem saída **validada** contra um modelo Pydantic (structured output). Texto
livre do LLM nunca chega ao grafo sem passar por esse schema.
"""

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from app.routing.cost import ModelSpec, Usage

MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
# Trecho máximo da mensagem de erro do provedor guardado na exceção (sem corpo inteiro).
_ERROR_SNIPPET = 200


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    parsed: T
    usage: Usage
    model_key: str
    model: str
    latency_ms: float
    cost_usd: Decimal
    attempts: int


class LLMError(Exception):
    """Erro de chamada a um LLM. A mensagem nunca contém segredos nem o prompt."""


class LLMUnavailableError(LLMError):
    """Provedor indisponível depois dos retries (429, 5xx, timeout ou rede)."""


class LLMRequestError(LLMError):
    """Requisição rejeitada pelo provedor (4xx que não adianta repetir)."""


class LLMOutputError(LLMError):
    """Resposta fora do schema, recusa ou resposta incompleta."""


class _RetryableStatusError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableStatusError | httpx.TimeoutException | httpx.TransportError)


def error_detail(response: httpx.Response) -> str:
    """Extrai só `type`/`code`/início da mensagem do erro do provedor."""
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        parts = [str(error.get(k)) for k in ("type", "code") if error.get(k)]
        message = str(error.get("message") or "")[:_ERROR_SNIPPET]
        return " ".join([*parts, message]).strip()
    if isinstance(error, str):
        return error[:_ERROR_SNIPPET]
    return response.reason_phrase


async def send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    provider: str,
    wait: wait_base | None = None,
) -> tuple[httpx.Response, int]:
    """Envia com retry exponencial em 429, 5xx, timeout e erro de rede.

    Devolve a resposta 2xx e o número de tentativas. Outros 4xx falham na hora.
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait or wait_exponential(multiplier=0.5, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=False,
    )
    attempts = 0
    try:
        async for attempt in retrying:
            with attempt:
                attempts += 1
                response = await send()
                if response.status_code == 429 or response.status_code >= 500:
                    raise _RetryableStatusError(response.status_code, error_detail(response))
                if response.is_error:
                    raise LLMRequestError(
                        f"{provider}: HTTP {response.status_code}: {error_detail(response)}"
                    )
                return response, attempts
    except RetryError as exc:
        cause = exc.last_attempt.exception()
        raise LLMUnavailableError(
            f"{provider}: indisponível após {attempts} tentativas: {type(cause).__name__}: {cause}"
        ) from cause
    raise AssertionError("inalcançável")  # pragma: no cover


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Schema JSON no formato exigido pelo modo estrito de structured output.

    Todo objeto recebe `additionalProperties: false` e todas as propriedades em `required`
    (campos com default passam a ser obrigatórios na saída do modelo). `title` e `default`
    são removidos porque não fazem parte do subconjunto aceito.
    """
    result = copy.deepcopy(schema.model_json_schema())

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


def parse_output[T: BaseModel](text: str, schema: type[T], provider: str) -> T:
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        # Não inclui o texto do modelo: ele pode ecoar conteúdo do lead.
        raise LLMOutputError(
            f"{provider}: saída fora do schema {schema.__name__} ({exc.error_count()} erro(s))"
        ) from None


def check_chat(spec: ModelSpec, provider: str) -> None:
    if spec.provider != provider or spec.kind != "chat":
        raise LLMRequestError(f"{spec.key} não é um modelo de chat do provedor {provider}")
