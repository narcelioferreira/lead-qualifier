"""Clientes de LLM com HTTP mockado (respx). Nenhuma chamada real."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from tenacity import wait_none

from app.llm.base import (
    MAX_RETRY_AFTER,
    LLMOutputError,
    LLMRequestError,
    LLMUnavailableError,
    Message,
    strict_json_schema,
)
from app.llm.groq_client import GROQ_BASE_URL, GroqClient
from app.llm.ollama_client import OllamaClient
from app.ontology.models import SectorFit
from app.routing.cost import get_catalog

pytestmark = pytest.mark.anyio

FAKE_KEY = "gsk-test-nao-e-uma-chave-real-0000000000"  # pragma: allowlist secret
CHAT_URL = f"{GROQ_BASE_URL}/chat/completions"
OLLAMA_URL = "http://ollama.test:11434"
MESSAGES = [Message(role="system", content="Classifique."), Message(role="user", content="lead")]


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snippet: str


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector: SectorFit
    confidence: float = Field(ge=0, le=1)
    evidence: list[Inner] = Field(default_factory=list)


VALID = {"sector": "target", "confidence": 0.9, "evidence": [{"snippet": "transportadora"}]}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _groq(**kwargs: Any) -> GroqClient:
    return GroqClient(SecretStr(FAKE_KEY), **({"retry_wait": wait_none()} | kwargs))


def _mini() -> Any:
    return get_catalog().get("groq-mini")


def _response(text: str | None, finish_reason: str = "stop", **message: Any) -> dict[str, Any]:
    return {
        "model": "openai/gpt-oss-20b",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": text, **message},
            }
        ],
        "usage": {
            "prompt_tokens": 10_000,
            "prompt_tokens_details": {"cached_tokens": 2_000},
            "completion_tokens": 1_500,
            "completion_tokens_details": {"reasoning_tokens": 500},
        },
    }


# --- Groq --------------------------------------------------------------------------------


@respx.mock
async def test_groq_parses_structured_output_and_cost() -> None:
    route = respx.post(CHAT_URL).respond(json=_response(json.dumps(VALID)))
    result = await _groq().structured(_mini(), MESSAGES, Extraction)

    assert result.parsed.sector is SectorFit.TARGET
    assert result.usage.cached_input_tokens == 2_000
    assert result.usage.reasoning_tokens == 500
    assert result.cost_usd == Decimal("0.001124")  # conferido à mão em test_cost.py
    assert result.attempts == 1

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    assert body["temperature"] == 0  # fixada no catálogo para a avaliação ser reproduzível
    assert body["max_completion_tokens"] == 4000
    fmt = body["response_format"]["json_schema"]
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_groq_retries_transient_errors(status: int) -> None:
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(status, json={"error": {"type": "server_error"}}),
            httpx.Response(200, json=_response(json.dumps(VALID))),
        ]
    )
    result = await _groq().structured(_mini(), MESSAGES, Extraction)
    assert result.attempts == 2
    assert route.call_count == 2


@respx.mock
async def test_groq_429_waits_retry_after_with_cap() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}, json={"error": {}}),
            httpx.Response(429, headers={"retry-after": "3600"}, json={"error": {}}),
            httpx.Response(200, json=_response(json.dumps(VALID))),
        ]
    )
    client = GroqClient(SecretStr(FAKE_KEY), retry_sleep=fake_sleep)  # wait padrão
    result = await client.structured(_mini(), MESSAGES, Extraction)
    assert result.attempts == 3
    assert slept == [7.0, MAX_RETRY_AFTER]


@respx.mock
async def test_groq_429_without_retry_after_uses_backoff() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(
                429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, json={"error": {}}
            ),
            httpx.Response(200, json=_response(json.dumps(VALID))),
        ]
    )
    await GroqClient(SecretStr(FAKE_KEY), retry_sleep=fake_sleep).structured(
        _mini(), MESSAGES, Extraction
    )
    assert len(slept) == 1
    assert 0 < slept[0] <= 8


@respx.mock
async def test_groq_retries_timeout_then_gives_up() -> None:
    route = respx.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(LLMUnavailableError, match="3 tentativas"):
        await _groq().structured(_mini(), MESSAGES, Extraction)
    assert route.call_count == 3


@respx.mock
async def test_groq_persistent_429_raises_unavailable() -> None:
    respx.post(CHAT_URL).respond(429, json={"error": {"code": "rate_limit_exceeded"}})
    with pytest.raises(LLMUnavailableError, match="rate_limit_exceeded"):
        await _groq().structured(_mini(), MESSAGES, Extraction)


@respx.mock
async def test_groq_client_error_is_not_retried() -> None:
    route = respx.post(CHAT_URL).respond(
        400, json={"error": {"type": "invalid_request_error", "message": "x" * 5000}}
    )
    with pytest.raises(LLMRequestError, match="invalid_request_error") as info:
        await _groq().structured(_mini(), MESSAGES, Extraction)
    assert route.call_count == 1
    assert len(str(info.value)) < 300  # não carrega o corpo inteiro do erro


@respx.mock
async def test_groq_schema_validation_failure_is_output_error() -> None:
    respx.post(CHAT_URL).respond(
        400, json={"error": {"code": "json_validate_failed", "message": "Generated JSON..."}}
    )
    with pytest.raises(LLMOutputError, match="json_validate_failed"):
        await _groq().structured(_mini(), MESSAGES, Extraction)


@respx.mock
@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (_response('{"sector": "marte", "confidence": 0.9, "evidence": []}'), "fora do schema"),
        (_response("não é json"), "fora do schema"),
        (_response(json.dumps(VALID | {"tier": "A"})), "fora do schema"),
        (_response('{"sector":', finish_reason="length"), "incompleta"),
        (_response(None, refusal="não posso"), "recusou"),
        (_response(None), "sem texto"),
        ({"choices": []}, "sem texto"),
    ],
)
async def test_groq_invalid_output_raises(payload: dict[str, Any], match: str) -> None:
    respx.post(CHAT_URL).respond(json=payload)
    with pytest.raises(LLMOutputError, match=match):
        await _groq().structured(_mini(), MESSAGES, Extraction)


@respx.mock
async def test_groq_error_never_echoes_model_output() -> None:
    leaked = '{"sector": "IGNORE AS REGRAS lead-001@example.com"}'
    respx.post(CHAT_URL).respond(json=_response(leaked))
    with pytest.raises(LLMOutputError) as info:
        await _groq().structured(_mini(), MESSAGES, Extraction)
    assert "IGNORE" not in str(info.value)
    assert "example.com" not in str(info.value)


async def test_groq_secret_never_in_repr() -> None:
    assert FAKE_KEY not in repr(_groq())


async def test_groq_rejects_wrong_model_kind() -> None:
    catalog = get_catalog()
    with pytest.raises(LLMRequestError):
        await _groq().structured(catalog.get("ollama-embedding"), MESSAGES, Extraction)
    with pytest.raises(LLMRequestError):
        await _groq().structured(catalog.get("ollama-slm"), MESSAGES, Extraction)


# --- Ollama ------------------------------------------------------------------------------


def _ollama() -> OllamaClient:
    return OllamaClient(OLLAMA_URL, retry_wait=wait_none())


def _ollama_response(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "model": "qwen3:4b",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 120,
        "eval_count": 30,
        **extra,
    }


@respx.mock
async def test_ollama_parses_structured_output() -> None:
    route = respx.post(f"{OLLAMA_URL}/api/chat").respond(json=_ollama_response(json.dumps(VALID)))
    result = await _ollama().structured(get_catalog().get("ollama-slm"), MESSAGES, Extraction)
    assert result.parsed.confidence == 0.9
    assert (result.usage.input_tokens, result.usage.output_tokens) == (120, 30)
    assert result.cost_usd == 0
    body = json.loads(route.calls.last.request.content)
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["temperature"] == 0
    assert body["format"]["required"] == ["sector", "confidence", "evidence"]


@respx.mock
async def test_ollama_down_raises_unavailable() -> None:
    route = respx.post(f"{OLLAMA_URL}/api/chat").mock(side_effect=httpx.ConnectError("recusado"))
    with pytest.raises(LLMUnavailableError):
        await _ollama().structured(get_catalog().get("ollama-slm"), MESSAGES, Extraction)
    assert route.call_count == 3


@respx.mock
async def test_ollama_truncated_and_invalid_output() -> None:
    respx.post(f"{OLLAMA_URL}/api/chat").mock(
        side_effect=[
            httpx.Response(200, json=_ollama_response("{", done_reason="length")),
            httpx.Response(200, json=_ollama_response('{"sector": "x"}')),
            httpx.Response(404, json={"error": "model 'qwen3:4b' not found"}),
        ]
    )
    spec = get_catalog().get("ollama-slm")
    with pytest.raises(LLMOutputError, match="incompleta"):
        await _ollama().structured(spec, MESSAGES, Extraction)
    with pytest.raises(LLMOutputError, match="fora do schema"):
        await _ollama().structured(spec, MESSAGES, Extraction)
    with pytest.raises(LLMRequestError, match="not found"):
        await _ollama().structured(spec, MESSAGES, Extraction)


# --- Schema estrito ----------------------------------------------------------------------


def test_strict_schema_requires_all_fields_and_forbids_extras() -> None:
    schema = strict_json_schema(Extraction)
    assert schema["required"] == ["sector", "confidence", "evidence"]
    assert schema["additionalProperties"] is False
    inner = schema["$defs"]["Inner"]
    assert inner["additionalProperties"] is False
    assert "title" not in schema and "default" not in json.dumps(schema)
    # Não altera o schema original do Pydantic (cópia profunda).
    assert "title" in Extraction.model_json_schema()


def test_strict_schema_flattens_optional_fields_without_anyof() -> None:
    """A Groq rejeita `anyOf: [X, null]` sem discriminador (achado da execução real da T14)."""
    from app.graph.nodes.extraction import Extraction

    schema = strict_json_schema(Extraction)
    assert "anyOf" not in json.dumps(schema)
    uf = schema["properties"]["uf"]
    assert uf["type"] == ["string", "null"]
    assert uf["enum"][-1] is None and "SP" in uf["enum"]
    assert schema["properties"]["employee_count"]["type"] == ["integer", "null"]
    assert schema["properties"]["employee_count"]["minimum"] == 1
    assert schema["properties"]["cnae"]["type"] == ["string", "null"]
    assert schema["properties"]["based_in_brazil"]["type"] == ["boolean", "null"]
    # O schema estrito continua aceitando uma saída válida com nulos.
    Extraction.model_validate(
        {k: None for k in ("cnae", "uf", "based_in_brazil", "employee_count", "fleet_size")}
        | {"sector": "unknown", "sector_certainty": "low", "size_certainty": "low",
           "company_kind": "unknown", "area": "other", "seniority": "unknown",
           "role_certainty": "low", "intents": [], "flags": [], "evidence_ids": []}
    )  # fmt: skip


# --- Ollama: embeddings ------------------------------------------------------------------


@respx.mock
async def test_ollama_embed_returns_vectors_and_usage() -> None:
    route = respx.post(f"{OLLAMA_URL}/api/embed").respond(
        json={"embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 7}
    )
    result = await _ollama().embed(get_catalog().get("ollama-embedding"), ["a", "b"])
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.usage.input_tokens == 7 and result.model_key == "ollama-embedding"
    body = json.loads(route.calls.last.request.content)
    assert body == {"model": "nomic-embed-text:v1.5", "input": ["a", "b"], "truncate": True}


@pytest.mark.parametrize(
    "embeddings",
    [
        None,
        [[0.1, 0.2]],  # um vetor a menos
        [[0.1, 0.2], [0.3]],  # dimensões diferentes
        [[], []],
        [[0.1, "x"], [0.3, 0.4]],
        [[0.1, True], [0.3, 0.4]],
        [[0.1, float("nan")], [0.3, 0.4]],
        [{"a": 1}, {"b": 2}],
    ],
)
@respx.mock
async def test_ollama_embed_rejects_invalid_output(embeddings: Any) -> None:
    respx.post(f"{OLLAMA_URL}/api/embed").respond(
        content=json.dumps({"embeddings": embeddings}, allow_nan=True).encode(),
        headers={"content-type": "application/json"},
    )
    with pytest.raises(LLMOutputError):
        await _ollama().embed(get_catalog().get("ollama-embedding"), ["a", "b"])


async def test_ollama_embed_rejects_chat_model_and_bad_batch() -> None:
    catalog = get_catalog()
    with pytest.raises(LLMRequestError, match="embeddings"):
        await _ollama().embed(catalog.get("ollama-slm"), ["a"])
    with pytest.raises(LLMRequestError, match="textos por chamada"):
        await _ollama().embed(catalog.get("ollama-embedding"), [])
