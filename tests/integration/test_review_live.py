"""Revisão humana com o Postgres real (T31): a execução parada sobrevive a um restart.

O "restart" fecha o pool do checkpointer e o engine da auditoria e abre outros: nada do
primeiro processo sobra além do que está no banco. LLM, busca e site continuam falsos.
"""

import uuid
from typing import Any

import psycopg
import pytest
from langgraph.types import Command
from pydantic import SecretStr

from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.graph.builder import build_graph
from app.graph.checkpoint import conninfo, forget, postgres_checkpointer, thread_config
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.graph.nodes.review import with_human_review
from app.routing.policy import MINI
from app.schemas import LeadInput
from tests.graph.test_mvp import ASSESSMENT, LEAD, SEARCH_OK, SITE_OK
from tests.graph.test_routing_graph import UNSURE, KeyedLLM

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def _graph(audit: AuditRepository, saver: Any) -> Any:
    llm = KeyedLLM({(MINI, Extraction): [UNSURE], (MINI, Assessment): [ASSESSMENT]})
    deps = MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK, audit=audit)  # type: ignore[arg-type]
    return build_graph(
        with_human_review(make_nodes(deps), audit), human_review=True, checkpointer=saver
    )


def _checkpoint_rows(url: SecretStr, run_id: str) -> int:
    with psycopg.connect(conninfo(url)) as conn:
        row = conn.execute("SELECT count(*) FROM checkpoints WHERE thread_id = %s", (run_id,))
        return int(row.fetchone()[0])  # type: ignore[index]


async def test_paused_run_survives_restart_and_resumes_once(migrated: str) -> None:
    url = SecretStr(migrated)

    # 1º processo: a API aceita o lead e o grafo para no `human_review`
    engine = create_engine(url)
    audit = AuditRepository(session_factory(engine))
    run_id = await audit.start_run(LeadInput.model_validate(LEAD), "v2", uuid.uuid4())
    config = thread_config(str(run_id))
    async with postgres_checkpointer(url) as saver:
        out = await _graph(audit, saver).ainvoke({"run_id": str(run_id), "raw_input": LEAD}, config)
    await engine.dispose()
    assert out["__interrupt__"]

    # 2º processo: só o banco sobrou
    engine = create_engine(url)
    audit = AuditRepository(session_factory(engine))
    paused = await audit.get_run(run_id)
    assert paused is not None
    assert (paused.status, paused.tier, paused.finished_at) == ("needs_review", "A", None)
    assert paused.review_requested_at is not None and paused.cost_usd > 0
    assert [s.node for s in paused.steps][-1] == "request_review"
    assert [r.run_id for r in await audit.list_runs(status="needs_review")] == [run_id]

    decision = {"action": "override", "tier": "B", "reviewer": "Ana Revisora", "comment": ""}
    assert await audit.claim_review(run_id, decision) == "claimed"
    assert await audit.claim_review(run_id, decision) == "not_awaiting"  # uma decisão só
    assert await audit.claim_review(uuid.uuid4(), decision) == "not_found"

    async with postgres_checkpointer(url) as saver:  # setup() de novo: idempotente
        graph = _graph(audit, saver)
        assert (await graph.aget_state(config)).next == ("human_review",)
        state = await graph.ainvoke(Command(resume=decision), config)
        assert _checkpoint_rows(url, str(run_id)) > 0
        await forget(saver, str(run_id))
    assert _checkpoint_rows(url, str(run_id)) == 0  # retenção mínima: o state tinha o e-mail

    assert state["status"] == "completed"
    done = await audit.get_run(run_id)
    await engine.dispose()
    assert done is not None
    assert (done.status, done.tier, done.score) == ("completed", "B", paused.score)
    assert done.result is not None and done.result["review"]["original_tier"] == "A"
    assert done.review == decision and done.finished_at is not None
    nodes = [s.node for s in done.steps]
    assert nodes.count("validate_input") == 1 and nodes.count("compute_score") == 1
    assert nodes[-3:] == ["human_review", "write_to_crm", "audit_log"]
    assert done.cost_usd == paused.cost_usd  # a retomada não chamou LLM (sem próximo passo)
