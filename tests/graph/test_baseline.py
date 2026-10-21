"""Baseline (T16): mesma pesquisa do MVP, mas o LLM decide o tier sozinho."""

import uuid
from typing import Any

import pytest

from app.graph.builder import build_baseline_graph
from app.graph.nodes.mvp import (
    BASELINE_PROMPT_VERSION,
    BaselineAnswer,
    MvpDeps,
    make_baseline_nodes,
)
from app.graph.state import QualificationState
from app.llm.base import LLMOutputError
from app.schemas import Tier
from tests.graph.test_mvp import LEAD, SEARCH_OK, SITE_OK, FakeAudit, FakeLLM

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _run(llm: FakeLLM, audit: FakeAudit | None = None) -> QualificationState:
    deps = MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK, audit=audit)  # type: ignore[arg-type]
    graph = build_baseline_graph(*make_baseline_nodes(deps))
    state: QualificationState = await graph.ainvoke(
        {"run_id": str(uuid.uuid4()), "raw_input": LEAD}
    )
    return state


async def test_baseline_uses_llm_tier_and_score() -> None:
    answer = BaselineAnswer(
        tier=Tier.B, score=68, rationale="Transportadora com pedido de proposta."
    )
    audit = FakeAudit()
    state = await _run(FakeLLM({BaselineAnswer: [answer]}), audit)
    result = state["result"]
    assert (result.tier, result.score) == (Tier.B, 68)  # vem do LLM, sem rubrica
    assert result.criteria == [] and result.prompt_version == BASELINE_PROMPT_VERSION
    assert state["status"] == "completed"
    assert [s.node for s in state["steps"]] == [
        "validate_input",
        "research",
        "classify",
        "audit_log",
    ]
    assert audit.records[0]["status"] == "completed"
    assert audit.records[0]["prompt_version"] == BASELINE_PROMPT_VERSION


async def test_baseline_prompt_has_same_evidence_and_delimitation() -> None:
    llm = FakeLLM({BaselineAnswer: [BaselineAnswer(tier=Tier.A, score=90, rationale="x")]})
    await _run(llm)
    system, user = llm.calls[BaselineAnswer][0]
    assert "Desqualificam (tier D)" in system.content
    assert "[E2] company_site https://gobor.com.br/" in user.content
    assert "lead-001@example.com" not in user.content


async def test_baseline_invalid_output_twice_fails() -> None:
    error = LLMOutputError("x")
    state = await _run(FakeLLM({BaselineAnswer: [error, error]}))
    assert state["status"] == "failed"
    assert "result" not in state


def test_baseline_answer_rejects_out_of_range() -> None:
    for bad in ({"score": 101}, {"tier": "E"}, {"extra": 1}):
        data: dict[str, Any] = {"tier": "A", "score": 50, "rationale": "x"} | bad
        with pytest.raises(ValueError):
            BaselineAnswer.model_validate(data)
