"""Relatório comparativo (T27) e os campos da configuração `rag` no runner. Sem rede."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.audit.repository import StepRecord
from app.graph.nodes import next_step
from app.schemas import NextStep, QualificationResult, Tier
from evals import compare, run
from evals.compare import mcnemar_exact, paired, render_comparison
from evals.dataset import load_dataset
from evals.metrics import Prediction
from evals.run import PredictionRow, _row_from_state

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 26, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def row(lead_id: str, tier: Tier | None, config: str = "mvp", **extra: Any) -> PredictionRow:
    base: dict[str, Any] = {
        "id": lead_id, "config": config, "split": "dev", "run_id": "r", "tier": tier,
        "status": "completed" if tier else "failed", "finished_at": NOW, "prompt_version": "v2",
    }  # fmt: skip
    return PredictionRow.model_validate(base | extra)


def pred(lead_id: str, label: Tier, predicted: Tier | None) -> Prediction:
    return Prediction(id=lead_id, label=label, predicted=predicted, status="completed")


# --- estatística ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("only_a", "only_b", "expected"),
    [(0, 0, 1.0), (0, 3, 0.25), (3, 0, 0.25), (1, 6, 0.125), (5, 5, 1.0), (0, 10, 2 / 1024)],
)
def test_mcnemar_exact(only_a: int, only_b: int, expected: float) -> None:
    assert mcnemar_exact(only_a, only_b) == pytest.approx(expected)


def test_paired_counts_only_common_leads() -> None:
    a = [pred("L1", Tier.A, Tier.A), pred("L2", Tier.B, Tier.C), pred("L3", Tier.C, Tier.C),
         pred("L4", Tier.D, None), pred("L9", Tier.A, Tier.A)]  # fmt: skip
    b = [pred("L1", Tier.A, Tier.A), pred("L2", Tier.B, Tier.B), pred("L3", Tier.C, Tier.B),
         pred("L4", Tier.D, Tier.D)]  # fmt: skip
    result = paired(a, b)
    assert (result.n, result.both_right, result.only_a, result.only_b, result.both_wrong) == (
        4, 1, 1, 2, 0,
    )  # fmt: skip
    assert result.delta == pytest.approx(0.25)
    low, high = result.delta_ci
    assert low <= result.delta <= high
    assert paired(a, b).delta_ci == result.delta_ci  # semente fixa: reproduzível
    with pytest.raises(ValueError, match="em comum"):
        paired(a[:1], [pred("LX", Tier.A, Tier.A)])


# --- relatório -----------------------------------------------------------------------------


def test_comparison_report_lists_changes_and_rag_metrics() -> None:
    labels = {"L1": Tier.A, "L2": Tier.B, "L3": Tier.C, "L4": Tier.D}
    mvp = [row("L1", Tier.A), row("L2", Tier.C), row("L3", Tier.C), row("L4", Tier.D),
           row("L2", Tier.A)]  # a última linha de cada lead vale (retomada)  # fmt: skip
    rag_extra: dict[str, Any] = {"config": "rag", "prompt_version": "v4"}
    rag = [
        row("L1", Tier.A, research_iterations=1, research_queries=1,
            next_step_citations=["playbook-tier-a", "case-x"], next_step_default=False,
            **rag_extra),
        row("L2", Tier.B, research_iterations=2, research_queries=2,
            next_step_citations=["playbook-tier-b"], next_step_default=False, **rag_extra),
        row("L3", Tier.B, research_iterations=2, research_queries=2,
            next_step_citations=["playbook-tier-b"], next_step_default=True, **rag_extra),
        row("L4", Tier.D, research_iterations=1, research_queries=1,
            next_step_citations=["playbook-tier-d"], next_step_default=True, **rag_extra),
        row("L5", Tier.A, **rag_extra),  # só numa das rodadas: fica de fora
    ]  # fmt: skip
    text = render_comparison(mvp, rag, labels, title="RAG × MVP")
    assert "dev (4 leads em comum)" in text
    assert "mvp (`v2`) × rag (`v4`)" in text
    assert "| L2 | B | A | B | corrigiu |" in text
    assert "| L3 | C | C | B | errou |" in text
    assert "1 só rag acertou, 1 só mvp acertou" in text
    assert "1 iteração(ões): 2 · 2 iteração(ões): 2 (média 1.50)" in text
    assert "2 gerados com RAG e 2 no passo padrão" in text
    assert "1 citam um case" in text and "`playbook-tier-b` (2)" in text
    assert "não** se distingue do ruído" in text


def test_report_without_rag_fields_has_no_rag_section_and_accepts_names() -> None:
    labels = {"L1": Tier.A}
    text = render_comparison([row("L1", Tier.A)], [row("L1", Tier.A)], labels, title="t",
                             names=("antes", "depois"))  # fmt: skip
    assert "Pesquisa agêntica" not in text
    assert "antes (`v2`) × depois (`v2`)" in text and "Nenhum." in text


def test_significant_difference_is_reported() -> None:
    labels = {f"L{i}": Tier.A for i in range(10)}
    a = [row(f"L{i}", Tier.B) for i in range(10)]
    b = [row(f"L{i}", Tier.A) for i in range(10)]
    assert "significativa a 5%" in render_comparison(a, b, labels, title="t")


def test_cli_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(row("L1", Tier.A).model_dump_json() + "\n", encoding="utf-8")
    b.write_text(row("L1", Tier.B, config="rag").model_dump_json() + "\n", encoding="utf-8")
    monkeypatch.setattr(compare, "load_labels", lambda: {"L1": Tier.A})
    monkeypatch.setattr(compare, "attack_ids", frozenset)
    out = tmp_path / "r.md"
    assert compare.main([str(a), str(b), "--out", str(out), "--title", "X"]) == 0
    assert out.read_text(encoding="utf-8").startswith("# X")


# --- runner: configuração `rag` e campos novos --------------------------------------------


def _state(route_reason: str, *, agentic: bool = True) -> dict[str, Any]:
    step = NextStep(action="a", owner="SDR", kb_citations=["playbook-tier-b", "case-y"])
    result = QualificationResult(
        run_id="r", tier=Tier.B, score=70, is_borderline=False, confidence=0.7,
        needs_human_review=False, criteria=[], rationale="ok", prompt_version="v4",
        cost_usd=0.0, next_step=step,
    )  # fmt: skip
    state: dict[str, Any] = {
        "status": "completed",
        "result": result,
        "steps": [StepRecord(node=next_step.NODE, route_reason=route_reason)],
    }
    if agentic:
        state |= {"research_iterations": 2, "research_queries": ["q1", "q2"]}
    return state


def test_row_records_research_and_next_step() -> None:
    item = load_dataset(split="dev")[0]
    r = _row_from_state(item, "rag", "r", _state(next_step.GENERATED), 10)
    assert (r.research_iterations, r.research_queries) == (2, 2)
    assert r.next_step_citations == ["playbook-tier-b", "case-y"]
    assert r.next_step_default is False
    fallback = _row_from_state(item, "rag", "r", _state(next_step.NO_CITATION), 10)
    assert fallback.next_step_default is True
    mvp = _row_from_state(item, "mvp", "r", {"status": "failed"}, 10)
    assert mvp.research_iterations is None and mvp.next_step_citations is None
    assert mvp.next_step_default is None
    no_loop = _row_from_state(item, "mvp", "r", _state(next_step.GENERATED, agentic=False), 1)
    assert no_loop.research_iterations is None


def test_runner_constants_match_the_node() -> None:
    assert run.NEXT_STEP_NODE == next_step.NODE
    assert run.GENERATED_WITH_RAG == next_step.GENERATED


def test_old_rows_still_load() -> None:
    rows = run.load_rows(Path("evals/runs/mvp-v2-test.jsonl"))
    assert len({r.id for r in rows}) == 30
    assert all(r.next_step_citations is None for r in rows)


async def test_rag_config_uses_agentic_research_and_next_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.graph import runtime

    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_graph(settings: Any, **kwargs: Any) -> AsyncIterator[tuple[str, None]]:
        seen.update(kwargs)
        yield "grafo", None

    monkeypatch.setattr(runtime, "production_graph", fake_graph)
    monkeypatch.setattr(run, "get_settings", lambda: None)
    assert "rag" in run.CONFIGS
    async with run.CONFIGS["rag"]("v4") as graph:
        assert graph == "grafo"
    assert seen == {"prompt_version": "v4", "agentic": True, "next_step": True}
