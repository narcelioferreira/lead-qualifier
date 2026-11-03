"""Revisão humana (T31): `interrupt()`, retomada com a decisão e checkpoint restrito, sem API."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from app.audit.repository import StepRecord
from app.graph import checkpoint
from app.graph.builder import GraphNodes, build_graph
from app.graph.checkpoint import SERIALIZER, thread_config
from app.graph.nodes.core import latency_ms
from app.graph.nodes.crm import note_text
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.graph.nodes.review import with_human_review
from app.graph.state import QualificationState
from app.routing.policy import MINI
from app.schemas import HumanReview, QualificationResult, ReviewDecision, Tier
from tests.graph.test_mvp import ASSESSMENT, LEAD, SEARCH_OK, SITE_OK, FakeAudit
from tests.graph.test_routing_graph import SURE, UNSURE, KeyedLLM

pytestmark = pytest.mark.anyio

APPROVE = {"action": "approve", "reviewer": "Ana Revisora"}
OVERRIDE = {
    "action": "override",
    "tier": "B",
    "reviewer": "Ana Revisora",
    "comment": "frota própria",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ReviewAudit(FakeAudit):
    """Auditoria falsa com o pedido de revisão (T31)."""

    def __init__(self, fail_request: bool = False) -> None:
        super().__init__()
        self.fail_request = fail_request
        self.requests: list[tuple[QualificationResult, list[StepRecord]]] = []

    async def request_review(
        self,
        run_id: uuid.UUID,
        result: QualificationResult,
        steps: Sequence[StepRecord],
        latency_ms: int,
    ) -> None:
        if self.fail_request:
            raise ConnectionError("banco fora do ar")
        self.requests.append((result, list(steps)))


class Harness:
    """Grafo com checkpointer; `restart()` monta outro grafo sobre o mesmo checkpointer."""

    def __init__(self, extraction: Extraction, audit: ReviewAudit | None = None, **flags: Any):
        self.saver = InMemorySaver(serde=SERIALIZER)
        self.audit = audit if audit is not None else ReviewAudit()
        self.extraction, self.flags = extraction, flags
        self.run_id = str(uuid.uuid4())
        self.config = thread_config(self.run_id)
        self.graph = self._build()

    def _build(self) -> Any:
        llm = KeyedLLM({(MINI, Extraction): [self.extraction], (MINI, Assessment): [ASSESSMENT]})
        deps = MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK, audit=self.audit)  # type: ignore[arg-type]
        nodes = with_human_review(self.flags.pop("nodes", make_nodes(deps)), self.audit)
        return build_graph(nodes, human_review=True, checkpointer=self.saver, **self.flags)

    def restart(self) -> None:
        self.graph = self._build()

    async def start(self) -> dict[str, Any]:
        out: dict[str, Any] = await self.graph.ainvoke(
            {"run_id": self.run_id, "raw_input": LEAD}, self.config
        )
        return out

    async def resume(self, decision: dict[str, Any]) -> QualificationState:
        state: QualificationState = await self.graph.ainvoke(Command(resume=decision), self.config)
        return state


async def test_uncertain_lead_stops_for_review_and_records_the_request() -> None:
    h = Harness(UNSURE)
    out = await h.start()

    [pending] = out["__interrupt__"]
    assert pending.value == {
        "run_id": h.run_id, "tier": "A", "score": 85.0, "is_borderline": False,
        "confidence": pytest.approx(0.4), "caps": [],
    }  # fmt: skip
    assert "result" not in out and "Gobor" not in str(pending.value)  # sem texto do lead
    snapshot = await h.graph.aget_state(h.config)
    assert snapshot.next == ("human_review",)
    # a fila de revisão já tem a execução, com resultado provisório e os passos até aqui
    [(result, steps)] = h.audit.requests
    assert (result.tier, result.needs_human_review, result.review) == (Tier.A, True, None)
    assert [s.node for s in steps][-2:] == ["compute_score", "request_review"]
    assert h.audit.records == []  # o audit_log ainda não rodou


async def test_approve_resumes_after_restart_and_completes_with_the_computed_tier() -> None:
    h = Harness(UNSURE)
    await h.start()
    h.restart()  # outro grafo, mesmo checkpointer: o state está no checkpoint, não no processo
    state = await h.resume(APPROVE)

    assert state["status"] == "completed"
    result = state["result"]
    assert result.tier is Tier.A and result.needs_human_review  # a regra continua registrada
    assert result.review is not None
    assert (result.review.action, result.review.original_tier) == ("approve", Tier.A)
    assert [s.node for s in state["steps"]][-4:] == [
        "request_review", "human_review", "write_to_crm", "audit_log",
    ]  # fmt: skip
    # o audit_log grava só os passos depois do pedido (os anteriores já foram gravados)
    [record] = h.audit.records
    assert [s.node for s in record["steps"]] == ["human_review", "write_to_crm", "audit_log"]
    assert record["status"] == "completed"


async def test_override_changes_the_tier_but_not_the_score() -> None:
    h = Harness(UNSURE)
    await h.start()
    state = await h.resume(OVERRIDE)

    result = state["result"]
    assert (result.tier, result.score) == (Tier.B, 85.0)  # o score continua o da rubrica
    assert result.review == HumanReview(
        action="override",
        original_tier=Tier.A,
        final_tier=Tier.B,
        reviewer="Ana Revisora",
        comment="frota própria",
        reviewed_at=result.review.reviewed_at if result.review else datetime.now(UTC),
    )
    [step] = [s for s in state["steps"] if s.node == "human_review"]
    assert step.route_reason == "revisão humana: override"
    note = note_text(state, result)
    assert "Revisão humana: tier alterado de A para B por Ana Revisora." in note
    assert "Revisão humana recomendada" not in note


async def test_next_step_uses_the_tier_decided_by_the_reviewer() -> None:
    seen: list[Tier] = []

    def next_step(state: QualificationState) -> dict[str, Any]:
        seen.append(state["score"].tier)
        return {}

    llm = KeyedLLM({(MINI, Extraction): [UNSURE], (MINI, Assessment): [ASSESSMENT]})
    nodes = make_nodes(MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK))  # type: ignore[arg-type]
    h = Harness(UNSURE, nodes=GraphNodes(**{**vars(nodes), "suggest_next_step": next_step}),
                next_step=True)  # fmt: skip
    await h.start()
    assert seen == []  # o próximo passo espera a decisão
    await h.resume(OVERRIDE)
    assert seen == [Tier.B]


async def test_confident_lead_does_not_stop() -> None:
    h = Harness(SURE)
    out = await h.start()
    assert "__interrupt__" not in out
    assert out["status"] == "completed" and "review" not in out
    assert h.audit.requests == []


async def test_if_the_request_is_not_recorded_the_lead_goes_on_without_review() -> None:
    """Ninguém acharia a execução para retomá-la: segue como antes da T31 (needs_review)."""
    h = Harness(UNSURE, audit=ReviewAudit(fail_request=True))
    out = await h.start()
    assert "__interrupt__" not in out
    assert out["status"] == "needs_review"
    assert "request_review: pedido não gravado (ConnectionError)" in out["errors"]
    [record] = h.audit.records
    assert record["steps"][0].node == "validate_input"  # grava todos os passos


async def test_invalid_decision_fails_inside_the_graph_too() -> None:
    """Defesa em profundidade: a API valida antes (422), e o nó valida de novo.

    O LangGraph guarda o valor do `resume` na tarefa: uma decisão inválida não é descartada
    para uma nova tentativa. Por isso a validação e a reserva acontecem antes do `Command`.
    """
    h = Harness(UNSURE)
    await h.start()
    with pytest.raises(ValidationError):
        await h.resume({"action": "override", "reviewer": "Ana Revisora"})  # sem tier
    assert h.audit.records == []  # nada é gravado como concluído


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "approve", "tier": "A", "reviewer": "Ana"},  # tier só no override
        {"action": "override", "reviewer": "Ana"},  # override sem tier
        {"action": "approve", "reviewer": "A"},  # revisor curto demais
        {"action": "approve", "reviewer": "Ana", "score": 99},  # campo extra
        {"action": "delete", "reviewer": "Ana"},
    ],
)
def test_review_decision_contract(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate(payload)


def test_review_decision_text_is_sanitized() -> None:
    decision = ReviewDecision.model_validate(
        {"action": "approve", "reviewer": "Ana​ Revisora", "comment": "ok‮"}
    )
    assert (decision.reviewer, decision.comment) == ("Ana Revisora", "ok")


def test_human_review_requires_a_checkpointer() -> None:
    with pytest.raises(ValueError, match="checkpointer"):
        build_graph(human_review=True)


def test_latency_does_not_count_the_wait_for_the_reviewer() -> None:
    import time

    state: Any = {"started_at": time.time() - 3600, "review_wait_ms": 3_590_000}
    assert 9_000 <= latency_ms(state) <= 11_000


class Intruder(BaseModel):
    payload: str


def test_checkpoint_only_rebuilds_the_types_of_the_state() -> None:
    """Classe fora de `STATE_TYPES` não é instanciada ao carregar o checkpoint."""
    loaded = SERIALIZER.loads_typed(SERIALIZER.dumps_typed(Intruder(payload="x")))
    assert loaded == {"payload": "x"} and not isinstance(loaded, Intruder)
    review = HumanReview(
        action="approve", original_tier=Tier.A, final_tier=Tier.A, reviewer="Ana",
        reviewed_at=datetime.now(UTC),
    )  # fmt: skip
    assert SERIALIZER.loads_typed(SERIALIZER.dumps_typed(review)) == review


async def test_whole_state_survives_the_checkpoint_round_trip() -> None:
    """Cada valor do state volta com o mesmo tipo (um tipo faltando em STATE_TYPES vira dict)."""
    h = Harness(UNSURE)
    await h.start()
    values = (await h.graph.aget_state(h.config)).values
    original = {k: v for k, v in values.items()}
    reloaded = SERIALIZER.loads_typed(SERIALIZER.dumps_typed(original))
    assert reloaded == original
    for key in ("lead", "profile", "score"):
        assert type(reloaded[key]) is type(original[key])
    assert type(reloaded["steps"][0]) is StepRecord
    assert type(reloaded["evidence"][0]) is type(original["evidence"][0])


def test_conninfo_drops_the_sqlalchemy_driver() -> None:
    from pydantic import SecretStr

    url = SecretStr("postgresql+psycopg://u:p@db:5432/lead")
    assert checkpoint.conninfo(url) == "postgresql://u:p@db:5432/lead"


def test_graph_without_review_is_unchanged_and_diagram_is_up_to_date() -> None:
    from app.graph.builder import MERMAID_REVIEW_PATH, to_mermaid

    full = {"agentic": True, "next_step": True, "guardrail": True}
    assert "human_review" not in to_mermaid(build_graph(**full))  # type: ignore[arg-type]
    diagram = to_mermaid(
        build_graph(**full, human_review=True, checkpointer=InMemorySaver())  # type: ignore[arg-type]
    )
    assert "compute_score -. &nbsp;review&nbsp; .-> request_review" in diagram
    assert "request_review -. &nbsp;wait&nbsp; .-> human_review" in diagram
    assert "request_review -. &nbsp;skip&nbsp; .-> suggest_next_step" in diagram
    assert MERMAID_REVIEW_PATH.read_text(encoding="utf-8") == diagram, (
        "rode `uv run python scripts/export_graph.py`"
    )
