"""Concordância entre anotadores: kappa de Cohen simples e ponderado (T09).

Os tiers são ordinais (A > B > C > D), então o kappa ponderado é a métrica principal: confundir
A com B é um erro menor que confundir A com D. A concordância humana é o teto realista do agente.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.schemas import Tier

TIERS: tuple[Tier, ...] = (Tier.A, Tier.B, Tier.C, Tier.D)
Weights = Literal["linear", "quadratic"] | None

# Faixas de Landis & Koch (1977), usadas só para descrever o valor no relatório.
_BANDS = ((0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial"))


def confusion_matrix(a: Sequence[Tier], b: Sequence[Tier]) -> list[list[int]]:
    """Matriz 4x4: linha = tier do anotador A, coluna = tier do anotador B."""
    _check_pairs(a, b)
    pos = {tier: i for i, tier in enumerate(TIERS)}
    matrix = [[0] * len(TIERS) for _ in TIERS]
    for x, y in zip(a, b, strict=True):
        matrix[pos[x]][pos[y]] += 1
    return matrix


def cohen_kappa(a: Sequence[Tier], b: Sequence[Tier], weights: Weights = None) -> float:
    """Kappa de Cohen: 1 - discordância observada / discordância esperada ao acaso."""
    matrix = confusion_matrix(a, b)
    n = len(a)
    k = len(TIERS)
    row = [sum(r) / n for r in matrix]
    col = [sum(matrix[i][j] for i in range(k)) / n for j in range(k)]

    def weight(i: int, j: int) -> float:
        if weights is None:
            return 0.0 if i == j else 1.0
        dist = abs(i - j) / (k - 1)
        return dist if weights == "linear" else dist**2

    observed = sum(weight(i, j) * matrix[i][j] / n for i in range(k) for j in range(k))
    expected = sum(weight(i, j) * row[i] * col[j] for i in range(k) for j in range(k))
    if expected == 0:
        # Os dois usaram uma única e mesma classe: concordância total, sem variação.
        return 1.0
    return 1.0 - observed / expected


def describe_kappa(value: float) -> str:
    if value < 0:
        return "pobre"
    for upper, name in _BANDS:
        if value <= upper:
            return name
    return "quase perfeita"


@dataclass(frozen=True)
class AgreementReport:
    annotators: tuple[str, str]
    n: int
    observed: float
    kappa: float
    kappa_linear: float
    kappa_quadratic: float
    matrix: list[list[int]]
    divergences: list[tuple[str, Tier, Tier]]


def agreement_report(
    ids: Sequence[str], a: Sequence[Tier], b: Sequence[Tier], annotators: tuple[str, str]
) -> AgreementReport:
    if len(ids) != len(a):
        raise ValueError("ids e rótulos com tamanhos diferentes")
    matrix = confusion_matrix(a, b)
    return AgreementReport(
        annotators=annotators,
        n=len(a),
        observed=sum(x == y for x, y in zip(a, b, strict=True)) / len(a),
        kappa=cohen_kappa(a, b),
        kappa_linear=cohen_kappa(a, b, "linear"),
        kappa_quadratic=cohen_kappa(a, b, "quadratic"),
        matrix=matrix,
        divergences=[(i, x, y) for i, x, y in zip(ids, a, b, strict=True) if x != y],
    )


def render_markdown(report: AgreementReport) -> str:
    first, second = report.annotators
    lines = [
        "# Concordância entre anotadores humanos (T09)",
        "",
        f"Anotadores: **{first}** × **{second}** · {report.n} leads",
        "",
        "| Métrica | Valor | Leitura (Landis & Koch) |",
        "|---|---:|---|",
        f"| Concordância observada | {report.observed:.1%} | — |",
        f"| Kappa de Cohen | {report.kappa:.3f} | {describe_kappa(report.kappa)} |",
        f"| Kappa ponderado linear | {report.kappa_linear:.3f} | "
        f"{describe_kappa(report.kappa_linear)} |",
        f"| Kappa ponderado quadrático | {report.kappa_quadratic:.3f} | "
        f"{describe_kappa(report.kappa_quadratic)} |",
        "",
        f"## Matriz de confusão (linhas = {first}, colunas = {second})",
        "",
        "| | " + " | ".join(TIERS) + " |",
        "|---|" + "---:|" * len(TIERS),
    ]
    lines += [
        f"| **{tier}** | " + " | ".join(str(v) for v in row) + " |"
        for tier, row in zip(TIERS, report.matrix, strict=True)
    ]
    lines += ["", f"## Divergências ({len(report.divergences)})", ""]
    if report.divergences:
        lines += [f"| Lead | {first} | {second} |", "|---|:-:|:-:|"]
        lines += [f"| {i} | {x} | {y} |" for i, x, y in report.divergences]
    else:
        lines.append("Nenhuma.")
    return "\n".join(lines) + "\n"


def _check_pairs(a: Sequence[Tier], b: Sequence[Tier]) -> None:
    if len(a) != len(b):
        raise ValueError("os anotadores rotularam quantidades diferentes de leads")
    if not a:
        raise ValueError("sem rótulos para comparar")
