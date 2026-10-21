"""Runner da avaliação: `uv run python -m evals.run --split dev --config mvp`.

Roda o grafo em cada lead do split, grava cada previsão em JSONL **assim que ela sai** (dá para
retomar com `--resume` depois de uma queda ou do limite diário da Groq) e gera o relatório em
Markdown comparando com o gabarito humano (`labels.jsonl`). O agente nunca vê os rótulos: eles
só entram no cálculo das métricas.

O split **test** é reservado às tasks de avaliação (uma rodada por configuração) e exige
`--confirm-test`.
"""

import argparse
import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.schemas import Tier
from evals.dataset import DATASET_PATH, DatasetItem, Split, load_dataset
from evals.labels import LABELS_PATH, FinalLabel, load_jsonl
from evals.metrics import Prediction, compute_metrics, render_report

RUNS_DIR = DATASET_PATH.parent / "runs"
REPORTS_DIR = DATASET_PATH.parent / "reports"
FIXTURES_DIR = DATASET_PATH.parent / "fixtures" / "companies"
# Pausa entre leads: o plano gratuito da Groq tem 8K tokens/min e o MVP gasta ~4,5K por lead.
DEFAULT_PAUSE_S = 20.0
MAX_ERRORS = 5
MAX_ERROR_CHARS = 300


class Graph(Protocol):
    async def ainvoke(self, input: Any, /) -> Any: ...


GraphFactory = Callable[[str], AbstractAsyncContextManager[Graph]]  # recebe a versão do prompt


@asynccontextmanager
async def _mvp(prompt_version: str) -> AsyncIterator[Graph]:
    from app.graph.runtime import production_graph

    settings = get_settings()
    async with production_graph(
        settings, fixtures_dir=FIXTURES_DIR, prompt_version=prompt_version
    ) as (graph, _audit):
        yield graph


@asynccontextmanager
async def _baseline(prompt_version: str) -> AsyncIterator[Graph]:
    from app.graph.runtime import baseline_graph

    async with baseline_graph(get_settings(), fixtures_dir=FIXTURES_DIR) as graph:
        yield graph


# Configurações avaliáveis (ablações da arquitetura, seção 11).
CONFIGS: dict[str, GraphFactory] = {"baseline": _baseline, "mvp": _mvp}
# Status sem tier que valem uma nova tentativa (`--retry-failed`). Rejeição não: é determinística.
RETRYABLE = frozenset({"failed", "error"})
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


class PredictionRow(BaseModel):
    """Uma linha do arquivo de previsões (sem dados pessoais: só id, tier e métricas)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    config: str
    split: Split
    run_id: str
    status: str
    tier: Tier | None = None
    score: float | None = None
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: str | None = None
    disqualifiers: list[str] = Field(default_factory=list)
    injection_rule: bool = False
    errors: list[str] = Field(default_factory=list)
    finished_at: datetime


def _row_from_state(
    item: DatasetItem, config: str, run_id: str, state: dict[str, Any], latency_ms: int
) -> PredictionRow:
    steps = state.get("steps", [])
    result = state.get("result")
    return PredictionRow(
        id=item.id,
        config=config,
        split=item.split,
        run_id=run_id,
        status=str(state.get("status", "failed")),
        tier=result.tier if result else None,
        score=result.score if result else None,
        cost_usd=sum((s.cost_usd for s in steps), Decimal(0)),
        latency_ms=latency_ms,
        input_tokens=sum(s.usage.input_tokens for s in steps),
        output_tokens=sum(s.usage.output_tokens for s in steps),
        prompt_version=state.get("prompt_version"),
        disqualifiers=list(result.disqualifiers) if result else [],
        injection_rule=bool(state.get("injection_hits")),
        errors=[str(e)[:MAX_ERROR_CHARS] for e in state.get("errors", [])[:MAX_ERRORS]],
        finished_at=datetime.now(UTC),
    )


async def run_eval(
    items: Sequence[DatasetItem],
    graph: Graph,
    out_path: Path,
    *,
    config: str,
    pause_s: float = DEFAULT_PAUSE_S,
    retry_failed: bool = False,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    log: Callable[[str], None] = print,
) -> list[PredictionRow]:
    """Roda os leads ainda não presentes em `out_path` e acrescenta uma linha por lead.

    Com `retry_failed`, leads cuja última linha falhou rodam de novo. Depois de
    `max_consecutive_failures` falhas seguidas o runner para (quase sempre é o limite diário
    da Groq): os leads restantes não são gastos à toa e a rodada pode ser retomada depois.
    """
    latest = {row.id: row for row in load_rows(out_path)} if out_path.exists() else {}
    done = {
        lead_id for lead_id, row in latest.items() if not (retry_failed and row.status in RETRYABLE)
    }
    pending = [item for item in items if item.id not in done]
    streak = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[PredictionRow] = []
    for index, item in enumerate(pending):
        if index:
            await sleep(pause_s)
        run_id = str(uuid.uuid4())
        raw = item.to_lead_input().model_dump(mode="json")  # só o lead: nada de metadados
        start = time.perf_counter()
        try:
            state = await graph.ainvoke({"run_id": run_id, "raw_input": raw})
        except Exception as exc:  # o runner registra e segue para o próximo lead
            state = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"]}
        latency = round((time.perf_counter() - start) * 1000)
        row = _row_from_state(item, config, run_id, state, latency)
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")
        rows.append(row)
        log(f"[{len(done) + index + 1}/{len(items)}] {item.id} {row.status} tier={row.tier}")
        streak = streak + 1 if row.status in RETRYABLE else 0
        if streak >= max_consecutive_failures:
            log(
                f"{streak} falhas seguidas: parando (provável limite da API). "
                "Retome com --resume <arquivo> --retry-failed."
            )
            break
    return rows


def load_rows(path: Path) -> list[PredictionRow]:
    return load_jsonl(path, PredictionRow)


def to_predictions(
    rows: Sequence[PredictionRow],
    labels: dict[str, Tier],
    attacks: frozenset[str] = frozenset(),
) -> list[Prediction]:
    missing = sorted({r.id for r in rows} - labels.keys())
    if missing:
        raise ValueError(f"leads sem rótulo no gabarito: {missing}")
    latest = {row.id: row for row in rows}  # numa retomada, vale a última linha de cada lead
    return [
        Prediction(
            id=row.id,
            label=labels[row.id],
            predicted=row.tier,
            status=row.status,
            cost_usd=row.cost_usd,
            latency_ms=row.latency_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            attack=row.id in attacks,
            disqualifiers=tuple(row.disqualifiers),
            injection_rule=row.injection_rule,
        )
        for row in latest.values()
    ]


def load_labels(path: Path = LABELS_PATH) -> dict[str, Tier]:
    return {label.id: label.tier for label in load_jsonl(path, FinalLabel)}


def attack_ids() -> frozenset[str]:
    """Leads adversariais pelas tags do dataset (metadado de avaliação, fora do agente)."""
    return frozenset(i.id for i in load_dataset() if any(t.startswith("attack:") for t in i.tags))


def write_report(rows: Sequence[PredictionRow], labels: dict[str, Tier], path: Path) -> str:
    predictions = to_predictions(rows, labels, attack_ids())
    first = rows[0]
    meta = {
        "Configuração": first.config,
        "Split": f"{first.split} ({len(predictions)} leads)",
        "Versão do prompt": first.prompt_version or "—",
        "Gerado em": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "Gabarito": "rotulagem humana (T09), anotador único: sem kappa humano de referência",
    }
    text = render_report(
        compute_metrics(predictions), title=f"Avaliação: {first.config} ({first.split})", meta=meta
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Avaliação do agente contra o gabarito humano")
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--resume", type=Path, help="arquivo de previsões a continuar")
    parser.add_argument("--report", type=Path, help="caminho do relatório Markdown")
    parser.add_argument("--limit", type=int, help="roda só os N primeiros leads (teste rápido)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_S, help="segundos entre leads")
    parser.add_argument("--prompt-version", default="v1", help="versão dos prompts (app/prompts/)")
    parser.add_argument("--retry-failed", action="store_true", help="refaz leads que falharam")
    parser.add_argument("--confirm-test", action="store_true", help="obrigatório para --split test")
    return parser


async def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.split == "test" and not args.confirm_test:
        print("o split test é reservado às avaliações (T16, T27, T30, T34): use --confirm-test")
        return 2
    items = load_dataset(split=args.split)[: args.limit]
    labels = load_labels()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = args.resume or RUNS_DIR / f"{args.config}-{args.split}-{stamp}.jsonl"
    async with CONFIGS[args.config](args.prompt_version) as graph:
        await run_eval(
            items,
            graph,
            out,
            config=args.config,
            pause_s=args.pause,
            retry_failed=args.retry_failed,
        )
    rows = [r for r in load_rows(out) if r.id in {i.id for i in items}]
    report = args.report or REPORTS_DIR / f"{args.config}-{args.split}.md"
    write_report(rows, labels, report)
    print(f"previsões: {out}\nrelatório: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
