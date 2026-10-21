"""Tipos comuns aos clientes de LLM: mensagens, resultado, erros e schema estrito.

Os clientes só devolvem saída **validada** contra um modelo Pydantic (structured output). Texto
livre do LLM nunca chega ao grafo sem passar por esse schema.
"""

import copy
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity.wait import wait_base

from app import retry
from app.retry import MAX_RETRY_AFTER as MAX_RETRY_AFTER  # reexportado para os clientes
from app.retry import Sleep
from app.routing.cost import ModelSpec, Usage

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
# Código de erro da Groq quando a saída gerada não bate com o schema.
_SCHEMA_FAILURE = "json_validate_failed"


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


class StructuredLLM(Protocol):
    """Cliente de LLM com saída estruturada (Groq, Ollama ou um mock nos testes)."""

    async def structured[T: BaseModel](
        self, spec: ModelSpec, messages: Sequence[Message], schema: type[T]
    ) -> LLMResult[T]: ...


class LLMError(Exception):
    """Erro de chamada a um LLM. A mensagem nunca contém segredos nem o prompt."""


class LLMUnavailableError(LLMError):
    """Provedor indisponível depois dos retries (429, 5xx, timeout ou rede)."""


class LLMRequestError(LLMError):
    """Requisição rejeitada pelo provedor (4xx que não adianta repetir)."""


class LLMOutputError(LLMError):
    """Resposta fora do schema, recusa ou resposta incompleta."""


async def send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    provider: str,
    wait: wait_base | None = None,
    sleep: Sleep | None = None,
) -> tuple[httpx.Response, int]:
    """`app.retry.send_with_retry` com os erros traduzidos para a hierarquia de LLM."""
    try:
        return await retry.send_with_retry(send, provider, wait, sleep)
    except retry.UpstreamUnavailableError as exc:
        raise LLMUnavailableError(str(exc)) from exc
    except retry.UpstreamRequestError as exc:
        if _SCHEMA_FAILURE in exc.detail:
            raise LLMOutputError(f"{provider}: saída fora do schema ({exc.detail})") from exc
        raise LLMRequestError(str(exc)) from exc


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Schema JSON no formato exigido pelo modo estrito de structured output.

    - Todo objeto recebe `additionalProperties: false` e todas as propriedades em `required`
      (campos com default passam a ser obrigatórios na saída do modelo).
    - Campo opcional (`X | None`, que o Pydantic gera como `anyOf: [X, null]`) vira a forma
      anulável `type: [..., "null"]`: a Groq rejeita `anyOf` sem discriminador.
    - `title` e `default` são removidos (fora do subconjunto aceito).
    """
    result = copy.deepcopy(schema.model_json_schema())
    defs: dict[str, Any] = result.get("$defs", {})

    def nullable(node: dict[str, Any]) -> dict[str, Any] | None:
        branches = node.get("anyOf")
        if not isinstance(branches, list) or len(branches) != 2:
            return None
        others = [b for b in branches if b != {"type": "null"}]
        if len(others) != 1:
            return None
        other = dict(others[0])
        ref = other.pop("$ref", None)
        if ref:
            other = {**copy.deepcopy(defs[ref.rsplit("/", 1)[-1]]), **other}
        if "type" not in other or isinstance(other["type"], list):
            return None
        merged = {k: v for k, v in node.items() if k != "anyOf"} | other
        merged["type"] = [other["type"], "null"]
        if "enum" in merged:
            merged["enum"] = [*merged["enum"], None]
        return merged

    def visit(node: Any) -> Any:
        if isinstance(node, dict):
            flat = nullable(node)
            if flat is not None:
                node = flat
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return {k: visit(v) for k, v in node.items()}
        if isinstance(node, list):
            return [visit(v) for v in node]
        return node

    strict: dict[str, Any] = visit(result)
    return strict


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
