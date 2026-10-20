import pytest

from app.schemas import Tier
from evals.agreement import (
    agreement_report,
    cohen_kappa,
    confusion_matrix,
    describe_kappa,
    render_markdown,
)

A, B, C, D = Tier.A, Tier.B, Tier.C, Tier.D

# Caso calculado à mão: um único erro vizinho (A → B) em 4 leads.
#   po = 3/4; marginais: anotador 1 = 1/4 cada tier; anotador 2 = A 0, B 1/2, C 1/4, D 1/4
#   simples:    pe = 1/4·(0 + 1/2 + 1/4 + 1/4) = 1/4        → κ = (3/4 − 1/4)/(3/4) = 2/3
#   linear:     Do = (1/3)/4 = 1/12; De = 1/4·(4·1/2 + 4·1/4 + 6·1/4)/3 = 3/8 → κ = 1 − 2/9 = 7/9
#   quadrático: Do = (1/9)/4 = 1/36; De = 1/4·(6·1/2 + 6·1/4 + 14·1/4)/9 = 2/9 → κ = 1 − 1/8 = 7/8
FIRST = [A, B, C, D]
SECOND = [B, B, C, D]


def test_kappa_hand_computed() -> None:
    assert cohen_kappa(FIRST, SECOND) == pytest.approx(2 / 3)
    assert cohen_kappa(FIRST, SECOND, "linear") == pytest.approx(7 / 9)
    assert cohen_kappa(FIRST, SECOND, "quadratic") == pytest.approx(7 / 8)


def test_perfect_agreement_is_one() -> None:
    labels = [A, B, C, D, A, D]
    for weights in (None, "linear", "quadratic"):
        assert cohen_kappa(labels, labels, weights) == pytest.approx(1.0)


def test_single_shared_class_is_one() -> None:
    assert cohen_kappa([D, D, D], [D, D, D]) == 1.0


def test_systematic_disagreement_is_negative() -> None:
    assert cohen_kappa([A, D, A, D], [D, A, D, A]) == pytest.approx(-1.0)


def test_distant_error_costs_more_when_weighted() -> None:
    near = cohen_kappa([A, B, C, D, A], [B, B, C, D, A], "linear")
    far = cohen_kappa([A, B, C, D, A], [D, B, C, D, A], "linear")
    assert far < near
    # O kappa simples não diferencia erro vizinho de erro distante.
    assert cohen_kappa([A, B, C, D, A], [B, B, C, D, A]) == pytest.approx(
        cohen_kappa([A, B, C, D, A], [D, B, C, D, A])
    )


def test_confusion_matrix_rows_are_first_annotator() -> None:
    matrix = confusion_matrix(FIRST, SECOND)
    assert matrix[0] == [0, 1, 0, 0]  # A do anotador 1 virou B do anotador 2
    assert sum(map(sum, matrix)) == 4


@pytest.mark.parametrize(("a", "b"), [([A], [A, B]), ([], [])])
def test_invalid_inputs_raise(a: list[Tier], b: list[Tier]) -> None:
    with pytest.raises(ValueError):
        cohen_kappa(a, b)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-0.1, "pobre"),
        (0.1, "leve"),
        (0.3, "razoável"),
        (0.5, "moderada"),
        (0.7, "substancial"),
        (0.9, "quase perfeita"),
    ],
)
def test_describe_kappa(value: float, expected: str) -> None:
    assert describe_kappa(value) == expected


def test_report_lists_divergences_and_renders() -> None:
    ids = ["L001", "L002", "L003", "L004"]
    report = agreement_report(ids, FIRST, SECOND, ("ana", "bia"))
    assert report.observed == pytest.approx(0.75)
    assert report.divergences == [("L001", A, B)]
    text = render_markdown(report)
    assert "| L001 | A | B |" in text
    assert "0.778" in text  # kappa linear = 7/9


def test_report_without_divergences() -> None:
    report = agreement_report(["L001", "L002"], [A, B], [A, B], ("ana", "bia"))
    assert "Nenhuma." in render_markdown(report)


def test_report_rejects_mismatched_ids() -> None:
    with pytest.raises(ValueError):
        agreement_report(["L001"], [A, B], [A, B], ("ana", "bia"))
