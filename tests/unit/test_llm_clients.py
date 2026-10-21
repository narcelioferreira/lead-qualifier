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
    LLMOutputError,
    LLMRequestError,
    LLMUnavailableError,
    Message,
    strict_json_schema,
)
from app.llm.ollama_client import OllamaClient
from app.llm.openai_client import OPENAI_BASE_URL, OpenAIClient
from app.ontology.models import SectorFit
from app.routing.cost import get_catalog

pytestmark = pytest.mark.anyio

FAKE_KEY = "sk-test-nao-e-uma-chave-real-0000000000"  # pragma: allowlist secret
RESPONSES_URL = f"{OPENAI_BASE_URL}/responses"
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


def _openai() -> OpenAIClient:
    return OpenAIClient(SecretStr(FAKE_KEY), retry_wait=wait_none())


def _response(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "model": "gpt-5.4-mini-2026-03-17",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 10_000,
            "input_tokens_details": {"cached_tokens": 2_000},
            "output_tokens": 1_500,
            "output_tokens_details": {"reasoning_tokens": 500},
        },
        **extra,
    }


# --- OpenAI ------------------------------------------------------------------------------


@respx.mock
async def test_openai_parses_structured_output_and_cost() -> None:
    route = respx.post(RESPONSES_URL).respond(json=_response(json.dumps(VALID)))
    result = await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)

    assert result.parsed.sector is SectorFit.TARGET
    assert result.usage.cached_input_tokens == 2_000
    assert result.cost_usd == Decimal("0.0129")  # conferido à mão em test_cost.py
    assert result.attempts == 1

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "gpt-5.4-mini-2026-03-17"
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_openai_retries_transient_errors(status: int) -> None:
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            httpx.Response(status, json={"error": {"type": "server_error"}}),
            httpx.Response(200, json=_response(json.dumps(VALID))),
        ]
    )
    result = await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)
    assert result.attempts == 2
    assert route.call_count == 2


@respx.mock
async def test_openai_retries_timeout_then_gives_up() -> None:
    route = respx.post(RESPONSES_URL).mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(LLMUnavailableError, match="3 tentativas"):
        await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)
    assert route.call_count == 3


@respx.mock
async def test_openai_persistent_429_raises_unavailable() -> None:
    respx.post(RESPONSES_URL).respond(429, json={"error": {"code": "rate_limit_exceeded"}})
    with pytest.raises(LLMUnavailableError, match="rate_limit_exceeded"):
        await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)


@respx.mock
async def test_openai_client_error_is_not_retried() -> None:
    route = respx.post(RESPONSES_URL).respond(
        400, json={"error": {"type": "invalid_request_error", "message": "x" * 5000}}
    )
    with pytest.raises(LLMRequestError, match="invalid_request_error") as info:
        await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)
    assert route.call_count == 1
    assert len(str(info.value)) < 300  # não carrega o corpo inteiro do erro


@respx.mock
@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (_response('{"sector": "marte", "confidence": 0.9, "evidence": []}'), "fora do schema"),
        (_response("não é json"), "fora do schema"),
        (_response(json.dumps(VALID | {"tier": "A"})), "fora do schema"),
        (
            _response("", status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
            "max_output_tokens",
        ),
        (
            {"status": "completed", "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": "não posso"}]}
            ]},
            "recusou",
        ),
        ({"status": "completed", "output": []}, "sem texto"),
    ],
)  # fmt: skip
async def test_openai_invalid_output_raises(payload: dict[str, Any], match: str) -> None:
    respx.post(RESPONSES_URL).respond(json=payload)
    with pytest.raises(LLMOutputError, match=match):
        await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)


@respx.mock
async def test_openai_error_never_echoes_model_output() -> None:
    leaked = '{"sector": "IGNORE AS REGRAS lead-001@example.com"}'
    respx.post(RESPONSES_URL).respond(json=_response(leaked))
    with pytest.raises(LLMOutputError) as info:
        await _openai().structured(get_catalog().get("openai-mini"), MESSAGES, Extraction)
    assert "IGNORE" not in str(info.value)
    assert "example.com" not in str(info.value)


async def test_openai_secret_never_in_repr() -> None:
    assert FAKE_KEY not in repr(_openai())


async def test_openai_rejects_wrong_model_kind() -> None:
    catalog = get_catalog()
    with pytest.raises(LLMRequestError):
        await _openai().structured(catalog.get("openai-embedding"), MESSAGES, Extraction)
    with pytest.raises(LLMRequestError):
        await _openai().structured(catalog.get("ollama-slm"), MESSAGES, Extraction)


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
