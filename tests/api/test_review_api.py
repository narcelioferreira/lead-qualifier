"""Revisão humana pela API (T31): fila `needs_review`, decisão, retomada e restart da API.

Grafo real do MVP com LLM, busca e site falsos; checkpointer em memória (o Postgres está nos
testes de integração) e auditoria no `MemoryAuditRepository`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.api.main import Services, create_app
from app.api.runner import Executor, Resumer, RunQueue
from app.audit.memory import MemoryAuditRepository
from app.graph.builder import build_graph
from app.graph.checkpoint import SERIALIZER, thread_config
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.graph.nodes.review import with_human_review
from app.routing.policy import MINI
from app.schemas import LeadInput, ReviewDecision
from tests.api.test_api import AUTH, _poll, settings
from tests.graph.test_mvp import ASSESSMENT, LEAD, SEARCH_OK, SITE_OK
from tests.graph.test_routing_graph import SURE, UNSURE, KeyedLLM

pytestmark = pytest.mark.anyio

APPROVE = {"action": "approve", "reviewer": "Ana Revisora"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class System:
    """Auditoria e checkpoint persistem; a API (fila, grafo) pode ser "reiniciada"."""

    def __init__(self) -> None:
        self.store = MemoryAuditRepository()
        self.saver = InMemorySaver(serde=SERIALIZER)
        self.extractions: list[Any] = []

    def _graph(self, extraction: Any) -> Any:
        llm = KeyedLLM({(MINI, Extraction): [extraction], (MINI, Assessment): [ASSESSMENT]})
        deps = MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK, audit=self.store)  # type: ignore[arg-type]
        nodes = with_human_review(make_nodes(deps), self.store)
        return build_graph(nodes, human_review=True, checkpointer=self.saver)

    def executor(self) -> Executor:
        async def execute(run_id: uuid.UUID, lead: LeadInput) -> None:
            graph = self._graph(self.extractions.pop(0))
            payload = {"run_id": str(run_id), "raw_input": lead.model_dump(mode="json")}
            await graph.ainvoke(payload, thread_config(str(run_id)))

        return execute

    def resumer(self) -> Resumer:
        async def resume(run_id: uuid.UUID, decision: ReviewDecision) -> None:
            graph = self._graph(None)  # a extração já está no checkpoint
            command = Command(resume=decision.model_dump(mode="json"))
            await graph.ainvoke(command, thread_config(str(run_id)))

        return resume

    async def client(
        self, *, review: bool = True, max_pending: int = 10
    ) -> AsyncIterator[httpx.AsyncClient]:
        queue = RunQueue(
            self.store,
            self.executor(),
            resumer=self.resumer() if review else None,
            prompt_version="v2",
            max_pending=max_pending,
        )
        app = create_app(settings(), Services(store=self.store, queue=queue))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
                yield c


async def _qualify(client: httpx.AsyncClient, until: str) -> tuple[str, dict[str, Any]]:
    response = await client.post("/v1/leads/qualify", json=LEAD, headers=AUTH)
    url = response.json()["status_url"]
    body = await _poll(client, url, lambda b: b["status"] == until)
    return url, body


async def test_uncertain_lead_waits_in_the_review_queue_and_resumes_with_the_decision() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, paused = await _qualify(client, "needs_review")
        assert paused["review_requested_at"] is not None and paused["finished_at"] is None
        assert paused["tier"] == "A" and paused["result"]["review"] is None
        assert paused["cost_usd"] != "0"  # os passos até a pausa já contam
        queue = (await client.get("/v1/runs?status=needs_review", headers=AUTH)).json()
        assert [i["run_id"] for i in queue["items"]] == [paused["run_id"]]

        response = await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
        assert response.status_code == 202
        assert response.headers["location"] == url
        done = await _poll(client, url, lambda b: b["status"] == "completed")

    review = done["result"]["review"]
    assert (review["action"], review["final_tier"], review["reviewer"]) == (
        "approve", "A", "Ana Revisora",
    )  # fmt: skip
    assert done["finished_at"] is not None and done["errors"] == []
    run = system.store.runs[uuid.UUID(done["run_id"])]
    nodes = [s.node for s in run["steps"]]
    assert nodes.count("validate_input") == 1 and nodes.count("audit_log") == 1  # sem duplicar
    assert nodes[-3:] == ["human_review", "write_to_crm", "audit_log"]
    assert run["review"] == {**APPROVE, "tier": None, "comment": ""}


async def test_paused_run_survives_an_api_restart() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
    # nova API (fila, grafo e executor novos); o checkpoint e a auditoria continuam
    async for client in system.client():
        override = {"action": "override", "tier": "C", "reviewer": "Ana Revisora"}
        assert (await client.post(f"{url}/review", json=override, headers=AUTH)).status_code == 202
        done = await _poll(client, url, lambda b: b["status"] == "completed")
    assert (done["tier"], done["score"]) == ("C", "85.0")


async def test_second_decision_gets_409() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
        assert (await client.post(f"{url}/review", json=APPROVE, headers=AUTH)).status_code == 202
        second = await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
        assert second.status_code == 409
        await _poll(client, url, lambda b: b["status"] == "completed")
        assert (await client.post(f"{url}/review", json=APPROVE, headers=AUTH)).status_code == 409


async def test_run_that_did_not_stop_gets_409_and_unknown_run_404() -> None:
    system = System()
    system.extractions = [SURE]
    async for client in system.client():
        url, _ = await _qualify(client, "completed")
        assert (await client.post(f"{url}/review", json=APPROVE, headers=AUTH)).status_code == 409
        unknown = await client.post(f"/v1/runs/{uuid.uuid4()}/review", json=APPROVE, headers=AUTH)
        assert unknown.status_code == 404


async def test_needs_review_without_checkpoint_is_not_resumable() -> None:
    """Execuções `needs_review` de antes da T31 (ou das avaliações) não têm o que retomar."""
    system = System()
    run_id = await system.store.start_run(LeadInput.model_validate(LEAD), "v2")
    system.store.runs[run_id]["status"] = "needs_review"
    async for client in system.client():
        response = await client.post(f"/v1/runs/{run_id}/review", json=APPROVE, headers=AUTH)
    assert response.status_code == 409
    assert system.store.runs[run_id]["status"] == "needs_review"


async def test_invalid_decision_gets_422_without_echo_and_does_not_consume_the_review() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
        bad = {"action": "override", "reviewer": "<script>alert(1)</script>", "tier": "Z"}
        response = await client.post(f"{url}/review", json=bad, headers=AUTH)
        assert response.status_code == 422
        assert "script" not in response.text
        assert (await client.post(f"{url}/review", json=APPROVE, headers=AUTH)).status_code == 202
        await _poll(client, url, lambda b: b["status"] == "completed")


async def test_review_requires_the_api_key() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
        response = await client.post(f"{url}/review", json=APPROVE)
        assert response.status_code == 401
        assert (await client.get(url, headers=AUTH)).json()["status"] == "needs_review"


async def test_api_without_human_review_answers_409() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client(review=False):
        url, _ = await _qualify(client, "needs_review")
        assert (await client.post(f"{url}/review", json=APPROVE, headers=AUTH)).status_code == 409


async def test_full_queue_answers_429_and_keeps_the_review() -> None:
    system = System()
    system.extractions = [UNSURE]
    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
    async for client in system.client(max_pending=0):
        response = await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
        assert response.status_code == 429 and response.headers["retry-after"] == "60"
        assert (await client.get(url, headers=AUTH)).json()["status"] == "needs_review"


async def test_failure_while_resuming_marks_the_run_failed() -> None:
    system = System()
    system.extractions = [UNSURE]

    async def broken(run_id: uuid.UUID, decision: ReviewDecision) -> None:
        raise RuntimeError("checkpoint corrompido em /var/lib/x")

    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
    queue = RunQueue(system.store, system.executor(), resumer=broken, prompt_version="v2")
    app = create_app(settings(), Services(store=system.store, queue=queue))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            assert (
                await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
            ).status_code == 202
            failed = await _poll(client, url, lambda b: b["status"] == "failed")
    assert failed["errors"] == ["falha interna (RuntimeError)"]  # sem o detalhe


async def test_decision_arriving_before_the_first_job_ends_does_not_fail_the_run() -> None:
    """Corrida: a decisão é reservada (`running`) antes de o job que parou terminar de conferir.

    O job original não pode tomar o `running` da decisão como "terminou sem gravar".
    """
    system = System()
    system.extractions = [UNSURE]
    paused, release = asyncio.Event(), asyncio.Event()
    execute = system.executor()

    async def slow_to_finish(run_id: uuid.UUID, lead: LeadInput) -> None:
        await execute(run_id, lead)  # o grafo para no `human_review`
        paused.set()
        await release.wait()  # o job ainda não fez a conferência final

    queue = RunQueue(
        system.store,
        slow_to_finish,
        resumer=system.resumer(),
        prompt_version="v2",
    )
    app = create_app(settings(), Services(store=system.store, queue=queue))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            response = await client.post("/v1/leads/qualify", json=LEAD, headers=AUTH)
            url = response.json()["status_url"]
            await paused.wait()
            assert (
                await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
            ).status_code == 202
            release.set()  # a retomada espera a vaga (1 por vez) que o job original libera
            done = await _poll(client, url, lambda b: b["status"] != "running")
    assert (done["status"], done["errors"]) == ("completed", [])


async def test_resume_that_does_not_record_the_result_is_failed() -> None:
    """A exceção da corrida acima vale só para o job original, não para a própria retomada."""
    system = System()
    system.extractions = [UNSURE]

    async def silent(run_id: uuid.UUID, decision: ReviewDecision) -> None:
        return None  # "retomou" sem o `audit_log` gravar nada

    async for client in system.client():
        url, _ = await _qualify(client, "needs_review")
    queue = RunQueue(system.store, system.executor(), resumer=silent, prompt_version="v2")
    app = create_app(settings(), Services(store=system.store, queue=queue))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            assert (
                await client.post(f"{url}/review", json=APPROVE, headers=AUTH)
            ).status_code == 202
            failed = await _poll(client, url, lambda b: b["status"] == "failed")
    assert failed["errors"] == ["execução terminou sem gravar o resultado"]
