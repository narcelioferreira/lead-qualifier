"""Montagem de produção da API (T21): executor do grafo, checagens de saúde e subida."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from langgraph.types import Command
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
        async def ainvoke(self, state: dict[str, Any], config: Any) -> dict[str, Any]:
            calls["state"], calls["config"] = state, config
            return state

    @asynccontextmanager
    async def fake_graph(settings: Settings, **kwargs: Any) -> AsyncIterator[tuple[Any, Any]]:
        calls["kwargs"] = kwargs
        yield FakeGraph(), None

    monkeypatch.setattr(production, "production_graph", fake_graph)
    run_id = uuid.uuid4()
    execute = production.graph_executor(_settings(api_write_crm=True, api_prompt_version="v2"))
    await execute(run_id, LeadInput.model_validate(LEAD))

    assert calls["kwargs"] == {"prompt_version": "v2", "write_crm": True, "checkpointer": None}
    assert calls["config"] == {"configurable": {"thread_id": str(run_id)}}
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


async def test_subida_marca_as_execucoes_orfas_como_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import integrity

    calls: list[str] = []

    class FakeRepo:
        def __init__(self, sessions: Any) -> None:
            pass

        async def fail_orphan_runs(self, message: str) -> int:
            calls.append(message)
            return 2

    class FakeEngine:
        async def dispose(self) -> None:
            calls.append("dispose")

    monkeypatch.setattr(integrity, "verify", lambda: "digest")
    monkeypatch.setattr(production, "AuditRepository", FakeRepo)
    monkeypatch.setattr(production, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(production, "session_factory", lambda engine: None)

    @asynccontextmanager
    async def fake_checkpointer(url: SecretStr) -> AsyncIterator[str]:
        calls.append("checkpointer")
        yield "saver"
        calls.append("checkpointer fechado")

    monkeypatch.setattr(production, "postgres_checkpointer", fake_checkpointer)
    async with production.production_services(_settings()) as services:
        assert set(services.checks) == {"postgres", "mcp", "ollama"}
    assert calls == [
        production.ORPHAN_MESSAGE, "checkpointer", "checkpointer fechado", "dispose",
    ]  # fmt: skip
    calls.clear()
    async with production.production_services(_settings(api_human_review=False)):
        pass
    assert calls == [production.ORPHAN_MESSAGE, "dispose"]  # sem revisão, sem checkpointer


# --- revisão humana (T31) -------------------------------------------------------------------


class FakeSaver:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class Snapshot:
    def __init__(self, interrupts: tuple[Any, ...]) -> None:
        self.interrupts = interrupts


class PausingGraph:
    """Para na 1ª chamada (interrupt pendente) e termina na retomada."""

    def __init__(self, paused: bool) -> None:
        self.paused = paused
        self.inputs: list[Any] = []

    async def ainvoke(self, payload: Any, config: Any) -> dict[str, Any]:
        self.inputs.append(payload)
        if isinstance(payload, Command):
            self.paused = False
        return {}

    async def aget_state(self, config: Any) -> Snapshot:
        return Snapshot(("interrupt",) if self.paused else ())


def _patch_graph(monkeypatch: pytest.MonkeyPatch, graph: PausingGraph) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_graph(settings: Settings, **kwargs: Any) -> AsyncIterator[tuple[Any, Any]]:
        seen.update(kwargs)
        yield graph, None

    monkeypatch.setattr(production, "production_graph", fake_graph)
    return seen


@pytest.mark.parametrize(("paused", "deleted"), [(True, False), (False, True)])
async def test_checkpoint_so_fica_para_quem_espera_revisao(
    monkeypatch: pytest.MonkeyPatch, paused: bool, deleted: bool
) -> None:
    saver, graph = FakeSaver(), PausingGraph(paused)
    seen = _patch_graph(monkeypatch, graph)
    run_id = uuid.uuid4()
    await production.graph_executor(_settings(), saver)(run_id, LeadInput.model_validate(LEAD))  # type: ignore[arg-type]
    assert seen["checkpointer"] is saver
    assert saver.deleted == ([str(run_id)] if deleted else [])


async def test_retomada_envia_a_decisao_e_apaga_o_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas import ReviewDecision

    saver, graph = FakeSaver(), PausingGraph(paused=True)
    _patch_graph(monkeypatch, graph)
    run_id = uuid.uuid4()
    decision = ReviewDecision(action="override", tier="B", reviewer="Ana Revisora")  # type: ignore[arg-type]
    await production.graph_resumer(_settings(), saver)(run_id, decision)  # type: ignore[arg-type]
    [command] = graph.inputs
    assert isinstance(command, Command)
    assert command.resume == {
        "action": "override", "tier": "B", "reviewer": "Ana Revisora", "comment": "",
    }  # fmt: skip
    assert saver.deleted == [str(run_id)]


async def test_retomada_sem_interrupt_no_checkpoint_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas import ReviewDecision

    saver, graph = FakeSaver(), PausingGraph(paused=False)
    _patch_graph(monkeypatch, graph)
    decision = ReviewDecision(action="approve", reviewer="Ana Revisora")
    with pytest.raises(production.NoPendingReviewError):
        await production.graph_resumer(_settings(), saver)(uuid.uuid4(), decision)  # type: ignore[arg-type]
    assert graph.inputs == [] and saver.deleted == []
