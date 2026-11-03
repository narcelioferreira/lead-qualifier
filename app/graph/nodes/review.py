"""Revisão humana (T31): o grafo para no `interrupt()` e só segue com a decisão do revisor.

    compute_score ─(regra de incerteza)─► request_review ─► human_review ─► próximo passo/CRM

- `request_review` grava na auditoria os passos até aqui e o resultado provisório, com status
  `needs_review` (a fila de `GET /v1/runs?status=needs_review`). Se a gravação falhar, o lead
  segue sem revisão, como antes da T31: ninguém acharia a execução para retomá-la;
- `human_review` chama o `interrupt()`: o state fica no checkpointer (Postgres em produção) e o
  processo pode reiniciar. `POST /v1/runs/{id}/review` retoma com `Command(resume=decisão)`.

Dois nós, e não um: ao retomar, o LangGraph reexecuta o nó interrompido desde o início. O
pedido à auditoria fica num nó que já terminou; o `human_review` não tem efeito colateral antes
do `interrupt()`.

A decisão humana é a única forma de mudar o tier fora da rubrica, e fica registrada ao lado do
tier calculado (`HumanReview`). O score não muda: o código continua sendo quem pontua.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from langgraph.types import interrupt

from app.audit.repository import StepRecord
from app.graph.nodes.core import build_result, latency_ms
from app.graph.state import QualificationState
from app.schemas import HumanReview, QualificationResult, ReviewDecision

if TYPE_CHECKING:  # o builder importa este módulo (nó `human_review`)
    from app.graph.builder import GraphNodes, Node


class ReviewAudit(Protocol):
    async def request_review(
        self,
        run_id: uuid.UUID,
        result: QualificationResult,
        steps: Sequence[StepRecord],
        latency_ms: int,
    ) -> None: ...


def review_request(state: QualificationState) -> dict[str, Any]:
    """O que o revisor vê no pedido (sem texto do lead: esse fica na execução)."""
    score = state["score"]
    return {
        "run_id": state["run_id"],
        "tier": score.tier.value,
        "score": score.score,
        "is_borderline": score.is_borderline,
        "confidence": state.get("confidence", 0.0),
        "caps": list(score.caps_applied),
    }


def make_request_review(audit: ReviewAudit | None) -> "Node":
    async def request_review(state: QualificationState) -> dict[str, Any]:
        step = StepRecord(node="request_review", output=review_request(state))
        steps = [*state.get("steps", []), step]
        update: dict[str, Any] = {"steps": [step], "review_requested_at": time.time()}
        if audit is None:  # testes de grafo: só o checkpointer
            return update | {"review_pending": True}
        try:
            await audit.request_review(
                uuid.UUID(state["run_id"]), build_result(state), steps, latency_ms(state)
            )
        except Exception as exc:
            return update | {
                "review_pending": False,
                "errors": [f"request_review: pedido não gravado ({type(exc).__name__})"],
            }
        return update | {"review_pending": True, "audited_steps": len(steps)}

    return request_review


def human_review(state: QualificationState) -> dict[str, Any]:
    """Para até a decisão do revisor; aplica o tier aprovado ou o escolhido no override."""
    decision = ReviewDecision.model_validate(interrupt(review_request(state)))
    score = state["score"]
    review = HumanReview(
        action=decision.action,
        original_tier=score.tier,
        final_tier=decision.tier or score.tier,
        reviewer=decision.reviewer,
        comment=decision.comment,
        reviewed_at=datetime.now(UTC),
    )
    waited = round((time.time() - state.get("review_requested_at", time.time())) * 1000)
    return {
        "review": review,
        "score": score.model_copy(update={"tier": review.final_tier}),
        "review_wait_ms": max(0, waited),
        "steps": [
            StepRecord(
                node="human_review",
                route_reason=f"revisão humana: {decision.action}",
                output=review.model_dump(mode="json"),
            )
        ],
    }


def with_human_review(nodes: "GraphNodes", audit: ReviewAudit | None) -> "GraphNodes":
    """Pedido de revisão gravado em `audit`. Use com `build_graph(..., human_review=True)`."""
    return replace(nodes, request_review=make_request_review(audit))
