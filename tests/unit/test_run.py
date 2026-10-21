"""Runner da avaliação com um grafo falso (sem rede, sem LLM)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.audit.repository import StepRecord
from app.routing.cost import Usage
from app.schemas import QualificationResult, Tier
from evals import run
from evals.dataset import load_dataset
from evals.run import PredictionRow, load_rows, run_eval, to_predictions, write_report

pytestmark = pytest.mark.anyio

ITEMS = load_dataset(split="dev")[:4]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeGraph:
    """Devolve tier A para todos, exceto um lead que explode e um que falha."""

    def __init__(self, explode: str | None = None, fail: str | None = None) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.explode, self.fail = explode, fail

    async def ainvoke(self, input: dict[str, Any], /) -> dict[str, Any]:
        self.inputs.append(input)
        name = input["raw_input"]["company_name"]
        if name == self.explode:
            raise RuntimeError("bug inesperado")
        step = StepRecord(node="normalize", usage=Usage(input_tokens=3000, output_tokens=400),
                          cost_usd=Decimal("0.0003"))  # fmt: skip
        if name == self.fail:
            return {"status": "failed", "errors": ["normalize: x"], "steps": [step]}
        result = QualificationResult(
            run_id=input["run_id"], tier=Tier.A, score=90.0, is_borderline=False,
            confidence=0.8, needs_human_review=False, criteria=[], rationale="ok",
            prompt_version="v1", cost_usd=0.0003,
        )  # fmt: skip
        return {"status": "completed", "result": result, "steps": [step], "prompt_version": "v1"}


async def test_run_writes_one_row_per_lead_and_pauses_between(tmp_path: Path) -> None:
    graph, slept = FakeGraph(), []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    out = tmp_path / "preds.jsonl"
    rows = await run_eval(
        ITEMS, graph, out, config="fake", pause_s=7, sleep=sleep, log=lambda _: None
    )
    assert [r.id for r in rows] == [i.id for i in ITEMS]
    assert [r.id for r in load_rows(out)] == [i.id for i in ITEMS]
    assert slept == [7, 7, 7]  # só entre leads
    first = rows[0]
    assert (first.tier, first.cost_usd, first.input_tokens) == (Tier.A, Decimal("0.0003"), 3000)
    # O grafo recebe só o lead: nada de rótulo, grupo-alvo, split ou tags.
    raw = graph.inputs[0]["raw_input"]
    assert not {"expected_group", "tags", "split", "id"} & raw.keys()


async def test_resume_skips_leads_already_done(tmp_path: Path) -> None:
    out = tmp_path / "preds.jsonl"
    await run_eval(ITEMS[:2], FakeGraph(), out, config="fake", pause_s=0, log=lambda _: None)
    graph = FakeGraph()
    rows = await run_eval(ITEMS, graph, out, config="fake", pause_s=0, log=lambda _: None)
    assert [r.id for r in rows] == [i.id for i in ITEMS[2:]]
    assert len(graph.inputs) == 2
    assert len(load_rows(out)) == 4


async def test_unexpected_exception_is_recorded_and_run_continues(tmp_path: Path) -> None:
    graph = FakeGraph(explode=ITEMS[1].company_name, fail=ITEMS[2].company_name)
    rows = await run_eval(ITEMS, graph, tmp_path / "p.jsonl", config="fake", pause_s=0,
                          log=lambda _: None)  # fmt: skip
    assert [r.status for r in rows] == ["completed", "error", "failed", "completed"]
    assert rows[1].errors == ["RuntimeError: bug inesperado"]
    assert rows[1].tier is None and rows[2].tier is None


def _row(lead_id: str, tier: Tier | None) -> PredictionRow:
    return PredictionRow(id=lead_id, config="fake", split="dev", run_id="r", status="completed",
                         tier=tier, finished_at=datetime.now(UTC))  # fmt: skip


def test_to_predictions_requires_labels_and_keeps_latest_row() -> None:
    rows = [_row("L002", Tier.C), _row("L002", Tier.A), _row("L005", None)]
    preds = to_predictions(rows, {"L002": Tier.A, "L005": Tier.D})
    assert [(p.id, p.predicted) for p in preds] == [("L002", Tier.A), ("L005", None)]
    with pytest.raises(ValueError, match="sem rótulo"):
        to_predictions([_row("L999", Tier.A)], {})


def test_write_report(tmp_path: Path) -> None:
    rows = [_row("L002", Tier.A), _row("L005", Tier.D)]
    text = write_report(rows, {"L002": Tier.A, "L005": Tier.B}, tmp_path / "r.md")
    assert (tmp_path / "r.md").read_text(encoding="utf-8") == text
    assert "Avaliação: fake (dev)" in text and "| Acurácia" in text


async def test_main_refuses_test_split_without_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await run.main(["--split", "test", "--config", "mvp"]) == 2
    assert "--confirm-test" in capsys.readouterr().out


async def test_main_end_to_end_with_fake_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def fake() -> AsyncIterator[FakeGraph]:
        yield FakeGraph()

    monkeypatch.setitem(run.CONFIGS, "fake", fake)
    out, report = tmp_path / "p.jsonl", tmp_path / "r.md"
    code = await run.main(["--split", "dev", "--config", "fake", "--limit", "3", "--pause", "0",
                           "--resume", str(out), "--report", str(report)])  # fmt: skip
    assert code == 0
    assert len(load_rows(out)) == 3
    assert "Split:** dev (3 leads)" in report.read_text(encoding="utf-8")
