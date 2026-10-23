"""Montagem de produção da API (T21): executor do grafo, checagens de saúde e subida."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from pydantic import SecretStr

from app.api import production
from app.config import Settings
from app.schemas import LeadInput
from tests.api.test_api import API_KEY
from tests.graph.test_mvp import LEAD

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _settings(**changes: Any) -> Settings:
    base: dict[str, Any] = {
        "api_key": SecretStr(API_KEY),
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost:1/db"),
        "groq_api_key": SecretStr("gsk-teste"),
        "tools_mcp_token": SecretStr("t" * 40),
    }
    return Settings(_env_file=None, **(base | changes))  # type: ignore[call-arg]


async def test_executor_roda_o_grafo_com_a_configuracao_da_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            calls["state"] = state
            return state

    @asynccontextmanager
    async def fake_graph(settings: Settings, **kwargs: Any) -> AsyncIterator[tuple[Any, Any]]:
        calls["kwargs"] = kwargs
        yield FakeGraph(), None

    monkeypatch.setattr(production, "production_graph", fake_graph)
    run_id = uuid.uuid4()
    execute = production.graph_executor(_settings(api_write_crm=True, api_prompt_version="v2"))
    await execute(run_id, LeadInput.model_validate(LEAD))

    assert calls["kwargs"] == {"prompt_version": "v2", "write_crm": True}
    assert calls["state"]["run_id"] == str(run_id)
    assert calls["state"]["raw_input"]["company_name"] == LEAD["company_name"]


def test_crm_e_desligado_por_padrao_na_api() -> None:
    settings = _settings()
    assert settings.api_write_crm is False
    assert settings.api_max_concurrent_runs == 1


async def test_health_do_ollama() -> None:
    checks = production.health_checks(_settings(), engine=None)  # type: ignore[arg-type]
    with respx.mock(base_url="http://localhost:11434") as router:
        router.get("/api/tags").respond(200, json={"models": []})
        await checks["ollama"]()
        router.get("/api/tags").respond(500)
        with pytest.raises(httpx.HTTPStatusError):
            await checks["ollama"]()


async def test_health_do_mcp_sem_token_falha() -> None:
    checks = production.health_checks(_settings(tools_mcp_token=None), engine=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="TOOLS_MCP_TOKEN"):
        await checks["mcp"]()


@pytest.mark.parametrize("missing", ["groq_api_key", "tools_mcp_token"])
async def test_api_nao_sobe_sem_as_chaves_do_grafo(missing: str) -> None:
    with pytest.raises(RuntimeError, match="obrigatórias para a API"):
        async with production.production_services(_settings(**{missing: None})):
            pass  # pragma: no cover


async def test_api_nao_sobe_com_configuracao_adulterada(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import integrity

    def drift() -> str:
        raise integrity.IntegrityError("rubric: alterado")

    monkeypatch.setattr(integrity, "verify", drift)
    with pytest.raises(integrity.IntegrityError):
        async with production.production_services(_settings()):
            pass  # pragma: no cover


def test_build_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(production, "get_settings", _settings)
    app = production.build_app()
    assert isinstance(app, FastAPI)
    assert {"/v1/leads/qualify", "/health"} <= set(app.openapi()["paths"])
