"""Retry de chamadas HTTP a serviços externos (LLMs, Tavily, HubSpot).

Repete em 429, 5xx, timeout e erro de rede, respeitando o `retry-after` do 429. Outros 4xx
falham na hora. As exceções carregam só status e um trecho curto do erro, nunca o corpo inteiro
nem segredos.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

MAX_ATTEMPTS = 3
# Teto de espera por tentativa quando o serviço manda `retry-after` (s).
MAX_RETRY_AFTER = 60.0
# Trecho máximo da mensagem de erro do serviço guardado na exceção.
ERROR_SNIPPET = 200

Sleep = Callable[[float], Awaitable[None]]


class UpstreamError(Exception):
    """Erro de um serviço externo."""


class UpstreamUnavailableError(UpstreamError):
    """Serviço indisponível depois dos retries (429, 5xx, timeout ou rede)."""


class UpstreamRequestError(UpstreamError):
    """Requisição rejeitada (4xx que não adianta repetir)."""

    def __init__(self, label: str, status: int, detail: str) -> None:
        super().__init__(f"{label}: HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class _RetryableStatusError(Exception):
    def __init__(self, status: int, detail: str, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableStatusError | httpx.TimeoutException | httpx.TransportError)


def _retry_after(response: httpx.Response) -> float | None:
    """Segundos do header `retry-after`. Datas HTTP são ignoradas (cai no backoff)."""
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


class wait_retry_after(wait_base):  # noqa: N801 - segue a convenção de nomes do tenacity
    """Espera o `retry-after` do serviço (com teto); sem o header, usa o backoff padrão."""

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
    """Extrai só `type`/`code`/início da mensagem de erro (formatos OpenAI, Tavily e HubSpot)."""
    try:
        body: Any = response.json()
    except ValueError:
        return response.reason_phrase
    if isinstance(body, dict) and body.get("category"):  # formato do HubSpot
        message = str(body.get("message") or "")[:ERROR_SNIPPET]
        return f"{body['category']} {message}".strip()
    error = body.get("error") or body.get("detail") if isinstance(body, dict) else None
    if isinstance(error, dict):
        parts = [str(error.get(k)) for k in ("type", "code") if error.get(k)]
        message = str(error.get("message") or error.get("error") or "")[:ERROR_SNIPPET]
        return " ".join([*parts, message]).strip()
    if isinstance(error, str):
        return error[:ERROR_SNIPPET]
    return response.reason_phrase


async def send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    label: str,
    wait: wait_base | None = None,
    sleep: Sleep | None = None,
) -> tuple[httpx.Response, int]:
    """Envia com retry e devolve a resposta 2xx e o número de tentativas."""
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
                    raise UpstreamRequestError(label, status, error_detail(response))
                return response, attempts
    except RetryError as exc:
        cause = exc.last_attempt.exception()
        raise UpstreamUnavailableError(
            f"{label}: indisponível após {attempts} tentativas: {type(cause).__name__}: {cause}"
        ) from cause
    raise AssertionError("inalcançável")  # pragma: no cover
