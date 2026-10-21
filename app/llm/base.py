"""Tipos comuns aos clientes de LLM: mensagens, resultado, erros, retry e schema estrito.

Os clientes só devolvem saída **validada** contra um modelo Pydantic (structured output). Texto
livre do LLM nunca chega ao grafo sem passar por esse schema.
"""

import asyncio
import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from app.routing.cost import ModelSpec, Usage

MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
# Teto de espera por tentativa quando o provedor manda `retry-after` (s).
MAX_RETRY_AFTER = 60.0
# Código de erro da Groq quando a saída gerada não bate com o schema.
_SCHEMA_FAILURE = "json_validate_failed"
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
    def __init__(self, status: int, detail: str, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableStatusError | httpx.TimeoutException | httpx.TransportError)


def _retry_after(response: httpx.Response) -> float | None:
    """Segundos do header `retry-after` (a Groq envia em todo 429). Datas HTTP são ignoradas."""
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


class wait_retry_after(wait_base):  # noqa: N801 - segue a convenção de nomes do tenacity
    """Espera o `retry-after` do provedor (com teto); sem o header, usa o backoff padrão."""

    def __init__(self, fallback: wait_base, cap: float = MAX_RETRY_AFTER) -> None:
        self.fallback = fallback
        self.cap = cap

    def __call__(self, retry_state: RetryCallState) -> float:
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome else None
        if isinstance(exc, _RetryableStatusError) and exc.retry_after is not None:
            return min(exc.retry_after, self.cap)
        return float(self.fallback(retry_state))


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
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> tuple[httpx.Response, int]:
    """Envia com retry em 429, 5xx, timeout e erro de rede.

    Respeita o `retry-after` do 429 (limites do plano gratuito) e, sem ele, usa backoff
    exponencial. Devolve a resposta 2xx e o número de tentativas. Outros 4xx falham na hora.
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait or wait_retry_after(wait_exponential(multiplier=0.5, max=8)),
        retry=retry_if_exception(_is_retryable),
        reraise=False,
        sleep=sleep or asyncio.sleep,
    )
    attempts = 0
    try:
        async for attempt in retrying:
            with attempt:
                attempts += 1
                response = await send()
                status = response.status_code
                if status == 429 or status >= 500:
                    raise _RetryableStatusError(
                        status, error_detail(response), _retry_after(response)
                    )
                if response.is_error:
                    detail = error_detail(response)
                    if _SCHEMA_FAILURE in detail:
                        raise LLMOutputError(f"{provider}: saída fora do schema ({detail})")
                    raise LLMRequestError(f"{provider}: HTTP {status}: {detail}")
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
