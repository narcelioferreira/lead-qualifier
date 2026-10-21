import math
import random
from decimal import Decimal

import numpy as np
import pytest
from sklearn.metrics import cohen_kappa_score

from app.schemas import Tier
from evals.agreement import cohen_kappa
from evals.metrics import (
    Prediction,
    accuracy,
    bootstrap_ci,
    compute_metrics,
    confusion,
    kappa,
    per_class,
    percentile,
    render_report,
)

A, B, C, D = Tier.A, Tier.B, Tier.C, Tier.D


def _preds(labels: list[Tier], predicted: list[Tier | None]) -> list[Prediction]:
    return [
        Prediction(
            id=f"L{i:03d}",
            label=label,
            predicted=pred,
            status="completed" if pred else "failed",
            cost_usd=Decimal("0.0004"),
            latency_ms=1000 * (i + 1),
            input_tokens=3000,
            output_tokens=500,
        )
        for i, (label, pred) in enumerate(zip(labels, predicted, strict=True))
    ]


LABELS = [A, A, B, B, C, D]


def test_perfect_predictions() -> None:
    m = compute_metrics(_preds(LABELS, list(LABELS)))
    assert m.accuracy == 1.0
    assert m.accuracy_ci == (1.0, 1.0)  # sem variação em nenhuma reamostra
    assert m.kappa_linear == pytest.approx(1.0)
    assert all(c.precision == 1.0 and c.recall == 1.0 for c in m.per_class.values())
    assert m.failures == {}


def test_all_wrong_predictions() -> None:
    wrong = [D, D, A, A, A, A]
    m = compute_metrics(_preds(LABELS, wrong))
    assert m.accuracy == 0.0
    assert all(c.recall == 0.0 for c in m.per_class.values())
    assert m.kappa_linear is not None and m.kappa_linear < 0


# Caso misto calculado à mão:
#   gabarito: A A B B C D
#   agente:   A B B — C A   (— = execução sem tier)
#   acertos: posições 0, 2, 4 → 3/6 = 50%
#   A: previstos 2 (pos. 0 e 5), 1 certo → precisão 1/2; suporte 2 → revocação 1/2
#   B: previstos 2 (pos. 1 e 2), 1 certo → 1/2; suporte 2 → 1/2
#   C: previsto 1, certo → 1; suporte 1 → 1
#   D: nunca previsto → precisão indefinida; suporte 1 → revocação 0
MIXED = _preds(LABELS, [A, B, B, None, C, A])


def test_mixed_case_hand_computed() -> None:
    assert accuracy(MIXED) == 0.5
    classes = per_class(MIXED)
    assert (classes[A].precision, classes[A].recall) == (0.5, 0.5)
    assert (classes[B].precision, classes[B].recall) == (0.5, 0.5)
    assert (classes[C].precision, classes[C].recall) == (1.0, 1.0)
    assert (classes[D].precision, classes[D].recall, classes[D].support) == (None, 0.0, 1)
    assert confusion(MIXED) == [
        [1, 1, 0, 0, 0],
        [0, 1, 0, 0, 1],  # o B sem tier vai para a última coluna
        [0, 0, 1, 0, 0],
        [1, 0, 0, 0, 0],
    ]
    m = compute_metrics(MIXED)
    assert (m.n, m.completed, m.failures) == (6, 5, {"failed": 1})
    assert m.cost_total == Decimal("0.0024")
    assert m.cost_mean == Decimal("0.0004")
    assert (m.input_tokens, m.output_tokens) == (18000, 3000)


def test_kappa_uses_only_runs_with_tier_and_matches_sklearn() -> None:
    labels = ["A", "A", "B", "C", "D"]  # sem a posição 3, que não tem tier
    predicted = ["A", "B", "B", "C", "A"]
    for weights in ("linear", "quadratic", None):
        expected = cohen_kappa_score(
            labels, predicted, labels=["A", "B", "C", "D"], weights=weights
        )
        assert kappa(MIXED, weights) == pytest.approx(expected)  # type: ignore[arg-type]


def test_kappa_matches_sklearn_on_random_cases() -> None:
    rng = random.Random(7)  # noqa: S311
    tiers = ["A", "B", "C", "D"]
    checked = 0
    for _ in range(200):
        n = rng.randint(5, 50)
        y1 = [rng.choice(tiers) for _ in range(n)]
        y2 = [rng.choice(tiers) if rng.random() < 0.6 else t for t in y1]
        for weights in ("linear", "quadratic", None):
            expected = cohen_kappa_score(y1, y2, labels=tiers, weights=weights)
            if math.isnan(expected):
                continue
            ours = cohen_kappa([Tier(t) for t in y1], [Tier(t) for t in y2], weights)  # type: ignore[arg-type]
            assert ours == pytest.approx(expected, abs=1e-12)
            checked += 1
    assert checked > 500


def test_kappa_without_any_tier_is_none() -> None:
    assert kappa(_preds([A, B], [None, None])) is None


@pytest.mark.parametrize("q", [0, 25, 50, 90, 95, 100])
def test_percentile_matches_numpy(q: float) -> None:
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6]
    assert percentile(values, q) == pytest.approx(float(np.percentile(values, q)))


def test_percentile_hand_computed() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)  # 3 + 0,85 × (4 − 3)
    assert percentile([], 50) == 0.0


def test_bootstrap_is_deterministic_and_contains_estimate() -> None:
    first = bootstrap_ci(MIXED, accuracy)
    assert first == bootstrap_ci(MIXED, accuracy)
    assert first is not None
    low, high = first
    assert low <= 0.5 <= high
    assert 0.0 <= low < high <= 1.0


def test_empty_predictions_raise() -> None:
    with pytest.raises(ValueError):
        compute_metrics([])


def test_report_renders_all_sections() -> None:
    text = render_report(compute_metrics(MIXED), title="Teste", meta={"Config": "mvp"})
    for piece in ("# Teste", "**Config:** mvp", "Acurácia", "Kappa ponderado linear (5 com tier)",
                  "| **B** | 0 | 1 | 0 | 0 | 1 |", "| D | — | 0.0% | 1 |", "US$ 0.002400",
                  "Execuções sem tier | 1"):  # fmt: skip
        assert piece in text, piece
