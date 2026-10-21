"""Métricas da avaliação: acurácia, kappa ponderado, matriz de confusão, precisão/recall,
IC 95% por bootstrap, custo e latência.

Uma execução que falha (sem tier) conta como **erro** na acurácia e na revocação: assim a
métrica não fica inflada por leads que o agente não conseguiu qualificar. O kappa usa só as
execuções com tier, e o relatório mostra quantas foram.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.schemas import Tier
from evals.agreement import TIERS, Weights, cohen_kappa

BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 42


@dataclass(frozen=True)
class Prediction:
    id: str
    label: Tier
    predicted: Tier | None  # None = execução sem tier (falha ou rejeição)
    status: str
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ClassMetrics:
    precision: float | None  # None quando a classe nunca foi prevista
    recall: float | None  # None quando a classe não existe no gabarito
    support: int


@dataclass(frozen=True)
class EvalMetrics:
    n: int
    completed: int
    accuracy: float
    accuracy_ci: tuple[float, float]
    kappa_linear: float | None
    kappa_linear_ci: tuple[float, float] | None
    kappa: float | None
    confusion: list[list[int]]  # linhas = gabarito A–D; colunas = previsto A–D + "sem tier"
    per_class: dict[Tier, ClassMetrics]
    cost_total: Decimal
    cost_mean: Decimal
    cost_p50: float
    cost_p95: float
    latency_p50: float
    latency_p95: float
    input_tokens: int
    output_tokens: int
    failures: dict[str, int] = field(default_factory=dict)


def accuracy(predictions: Sequence[Prediction]) -> float:
    if not predictions:
        raise ValueError("sem previsões")
    return sum(p.predicted == p.label for p in predictions) / len(predictions)


def confusion(predictions: Sequence[Prediction]) -> list[list[int]]:
    pos = {tier: i for i, tier in enumerate(TIERS)}
    matrix = [[0] * (len(TIERS) + 1) for _ in TIERS]
    for p in predictions:
        column = len(TIERS) if p.predicted is None else pos[p.predicted]
        matrix[pos[p.label]][column] += 1
    return matrix


def per_class(predictions: Sequence[Prediction]) -> dict[Tier, ClassMetrics]:
    result: dict[Tier, ClassMetrics] = {}
    for tier in TIERS:
        tp = sum(p.label == tier and p.predicted == tier for p in predictions)
        predicted = sum(p.predicted == tier for p in predictions)
        support = sum(p.label == tier for p in predictions)
        result[tier] = ClassMetrics(
            precision=tp / predicted if predicted else None,
            recall=tp / support if support else None,
            support=support,
        )
    return result


def kappa(predictions: Sequence[Prediction], weights: Weights = "linear") -> float | None:
    labels = [p.label for p in predictions if p.predicted is not None]
    predicted = [p.predicted for p in predictions if p.predicted is not None]
    return cohen_kappa(labels, predicted, weights) if labels else None


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil com interpolação linear (mesmo método padrão do numpy)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def bootstrap_ci(
    predictions: Sequence[Prediction],
    statistic: Callable[[Sequence[Prediction]], float | None],
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """IC 95% por bootstrap percentil, reamostrando leads com reposição (semente fixa)."""
    # Semente fixa para o IC ser reproduzível; não há uso de segurança aqui.
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    values = []
    for _ in range(samples):
        sample = [predictions[rng.randrange(len(predictions))] for _ in predictions]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    if not values:
        return None
    return percentile(values, 2.5), percentile(values, 97.5)


def compute_metrics(predictions: Sequence[Prediction]) -> EvalMetrics:
    if not predictions:
        raise ValueError("sem previsões")
    costs = [float(p.cost_usd) for p in predictions]
    latencies = [float(p.latency_ms) for p in predictions]
    total = sum((p.cost_usd for p in predictions), Decimal(0))
    failures: dict[str, int] = {}
    for p in predictions:
        if p.predicted is None:
            failures[p.status] = failures.get(p.status, 0) + 1
    acc_ci = bootstrap_ci(predictions, accuracy)
    return EvalMetrics(
        n=len(predictions),
        completed=sum(p.predicted is not None for p in predictions),
        accuracy=accuracy(predictions),
        accuracy_ci=acc_ci or (0.0, 0.0),
        kappa_linear=kappa(predictions, "linear"),
        kappa_linear_ci=bootstrap_ci(predictions, lambda s: kappa(s, "linear")),
        kappa=kappa(predictions, None),
        confusion=confusion(predictions),
        per_class=per_class(predictions),
        cost_total=total,
        cost_mean=total / len(predictions),
        cost_p50=percentile(costs, 50),
        cost_p95=percentile(costs, 95),
        latency_p50=percentile(latencies, 50),
        latency_p95=percentile(latencies, 95),
        input_tokens=sum(p.input_tokens for p in predictions),
        output_tokens=sum(p.output_tokens for p in predictions),
        failures=failures,
    )


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def render_report(metrics: EvalMetrics, *, title: str, meta: dict[str, str]) -> str:
    """Relatório em Markdown (evals/reports/)."""
    m = metrics
    lines = [f"# {title}", ""]
    lines += [f"- **{k}:** {v}" for k, v in meta.items()]
    lines += [
        "",
        "## Concordância com o gabarito humano",
        "",
        "| Métrica | Valor | IC 95% (bootstrap) |",
        "|---|---:|---|",
        f"| Acurácia (falha conta como erro) | {m.accuracy:.1%} | "
        f"{m.accuracy_ci[0]:.1%} – {m.accuracy_ci[1]:.1%} |",
    ]
    if m.kappa_linear is not None and m.kappa_linear_ci is not None:
        lines.append(
            f"| Kappa ponderado linear ({m.completed} com tier) | {m.kappa_linear:.3f} | "
            f"{m.kappa_linear_ci[0]:.3f} – {m.kappa_linear_ci[1]:.3f} |"
        )
    if m.kappa is not None:
        lines.append(f"| Kappa simples | {m.kappa:.3f} | — |")
    lines += [
        "",
        "## Matriz de confusão (linhas = gabarito, colunas = agente)",
        "",
        "| | A | B | C | D | sem tier |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| **{tier}** | " + " | ".join(str(v) for v in row) + " |"
        for tier, row in zip(TIERS, m.confusion, strict=True)
    ]
    lines += [
        "",
        "## Por classe",
        "",
        "| Tier | Precisão | Revocação | Suporte |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {tier} | {_pct(c.precision)} | {_pct(c.recall)} | {c.support} |"
        for tier, c in m.per_class.items()
    ]
    lines += [
        "",
        "## Custo e latência por lead",
        "",
        "| Métrica | Valor |",
        "|---|---:|",
        f"| Custo equivalente total | US$ {m.cost_total:.6f} |",
        f"| Custo médio | US$ {m.cost_mean:.6f} |",
        f"| Custo p50 / p95 | US$ {m.cost_p50:.6f} / {m.cost_p95:.6f} |",
        f"| Latência p50 / p95 | {m.latency_p50 / 1000:.1f} s / {m.latency_p95 / 1000:.1f} s |",
        f"| Tokens (entrada / saída) | {m.input_tokens:,} / {m.output_tokens:,} |",
        f"| Execuções sem tier | {sum(m.failures.values())} {m.failures or ''} |",
    ]
    return "\n".join(lines) + "\n"
