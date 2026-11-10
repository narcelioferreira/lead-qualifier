"""Custo × acurácia de todas as configurações (T30 e T34): tabela em Markdown e gráfico em SVG.

Lê as previsões gravadas de cada configuração (dev e test) e o gabarito humano. Não chama API.
O SVG não tem dependência externa (nada de matplotlib): é texto, versionado ao lado do relatório,
com tema claro e escuro (`prefers-color-scheme`) e um tooltip por ponto (`<title>`).

A configuração entregue (`api`, T34) aparece em destaque, com outra cor e o rótulo "(entregue)".

Uso: `uv run python -m evals.cost_chart` (escreve o SVG e imprime a tabela).
"""

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path

from evals.metrics import compute_metrics
from evals.run import REPORTS_DIR, RUNS_DIR, attack_ids, load_labels, load_rows, to_predictions


@dataclass(frozen=True)
class ConfigRuns:
    name: str
    description: str
    dev: str
    test: str
    highlight: bool = False


# Ordem = ordem das ablações da arquitetura (seção 11).
CONFIGS: tuple[ConfigRuns, ...] = (
    ConfigRuns("baseline", "prompt único, o LLM decide o tier", "baseline-dev", "baseline-test"),
    ConfigRuns("mvp", "ontologia + score em código", "mvp-v2-sec-dev", "mvp-v2-test"),
    ConfigRuns("rag", "+ pesquisa agêntica e próximo passo", "rag-v5-dev", "rag-v5-test"),
    ConfigRuns("routing", "+ guardrail e roteamento", "routing-v6-dev", "routing-v6-test"),
    ConfigRuns("large_only", "tudo no modelo maior", "large_only-v6-dev", "large_only-v6-test"),
    ConfigRuns("api", "configuração entregue: MVP + guardrail", "api-v6-dev", "api-v6-test", True),
)
SVG_PATH = REPORTS_DIR / "05-final-custo-acuracia.svg"
HIGHLIGHT_SUFFIX = " (entregue)"


@dataclass(frozen=True)
class Point:
    config: str
    split: str
    n: int
    accuracy: float
    accuracy_ci: tuple[float, float]
    kappa: float | None
    cost_mean: float
    tokens_mean: float
    latency_p50_ms: float
    highlight: bool = False


def load_points(configs: Sequence[ConfigRuns] = CONFIGS, runs_dir: Path = RUNS_DIR) -> list[Point]:
    """Um ponto por configuração e split com o arquivo de previsões gravado."""
    labels, attacks = load_labels(), attack_ids()
    points = []
    for config in configs:
        for split, stem in (("dev", config.dev), ("test", config.test)):
            path = runs_dir / f"{stem}.jsonl"
            if not path.exists():
                continue
            predictions = to_predictions(load_rows(path), labels, attacks)
            m = compute_metrics(predictions)
            points.append(
                Point(
                    config=config.name,
                    split=split,
                    n=m.n,
                    accuracy=m.accuracy,
                    accuracy_ci=m.accuracy_ci,
                    kappa=m.kappa_linear,
                    cost_mean=float(m.cost_mean),
                    tokens_mean=(m.input_tokens + m.output_tokens) / m.n,
                    latency_p50_ms=m.latency_p50,
                    highlight=config.highlight,
                )
            )
    return points


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".", ",")


def render_table(points: Sequence[Point]) -> str:
    lines = [
        "| Configuração | Split | Acurácia (IC 95%) | κ ponderado | Custo por lead | "
        "Tokens por lead | Latência p50 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for p in points:
        kappa = "—" if p.kappa is None else f"{p.kappa:.3f}".replace(".", ",")
        lines.append(
            f"| `{p.config}` | {p.split} ({p.n}) | {_pct(p.accuracy)} "
            f"({_pct(p.accuracy_ci[0])}–{_pct(p.accuracy_ci[1])}) | {kappa} | "
            f"US$ {p.cost_mean:.6f}".replace(".", ",")
            + f" | {p.tokens_mean:,.0f}".replace(",", ".")
            + f" | {p.latency_p50_ms / 1000:.1f} s |".replace(".", ",")
        )
    return "\n".join(lines)


# --- SVG ---------------------------------------------------------------------------------
# Dois painéis na mesma escala (dev à esquerda, test à direita), com o nome da configuração em
# cada ponto: uma cor só, sem legenda para decifrar.

PANEL_W, PANEL_H = 360, 300
LEFT, GAP, TOP, BOTTOM, RIGHT = 64, 76, 92, 58, 24
WIDTH = LEFT + 2 * PANEL_W + GAP + RIGHT
HEIGHT = TOP + PANEL_H + BOTTOM
X_MIN, X_MAX = 1e-4, 1e-2  # US$ por lead, escala log
Y_MIN, Y_MAX = 0.2, 1.0
X_TICKS = (1e-4, 1e-3, 1e-2)
X_MINOR = (3e-4, 3e-3)
Y_TICKS = (0.2, 0.4, 0.6, 0.8, 1.0)
PANELS = (("dev", "dev: 20 leads, usado no ajuste"), ("test", "test: 30 leads, rodada única"))

STYLE = """
.viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --grid:#e6e5e1; --mark:#2a78d6;
  --final:#c2410c; }
@media (prefers-color-scheme: dark) {
  .viz { --surface:#1a1a19; --ink:#f0efec; --ink-2:#c3c2b7; --grid:#33322f; --mark:#3987e5;
    --final:#f97316; }
}
.bg { fill: var(--surface); }
.title { fill: var(--ink); font: 600 16px system-ui, sans-serif; }
.panel { fill: var(--ink); font: 600 13px system-ui, sans-serif; }
.sub, .tick, .axis { fill: var(--ink-2); font: 12px system-ui, sans-serif; }
.label { fill: var(--ink); font: 600 12px system-ui, sans-serif; }
.grid { stroke: var(--grid); stroke-width: 1; }
.ci { stroke: var(--mark); stroke-width: 2; stroke-linecap: round; opacity: .45; }
.dot { fill: var(--mark); stroke: var(--surface); stroke-width: 2; }
.ci.final { stroke: var(--final); opacity: .6; }
.dot.final { fill: var(--final); }
.label.final { fill: var(--final); }
.halo { fill: var(--surface); stroke: var(--surface); stroke-width: 4; stroke-linejoin: round;
  font: 600 12px system-ui, sans-serif; }
"""


def _x(cost: float, origin: float) -> float:
    cost = min(max(cost, X_MIN), X_MAX)
    span = math.log10(X_MAX) - math.log10(X_MIN)
    return origin + (math.log10(cost) - math.log10(X_MIN)) / span * PANEL_W


def _y(value: float) -> float:
    value = min(max(value, Y_MIN), Y_MAX)
    return TOP + (Y_MAX - value) / (Y_MAX - Y_MIN) * PANEL_H


def _cost_label(cost: float) -> str:
    return f"US$ {cost:.4f}".rstrip("0").replace(".", ",")


CHAR_W, LABEL_H, DOT_R = 7, 12, 7  # largura média de um caractere do rótulo, altura e raio
# Posições candidatas do rótulo em relação ao ponto: (dx, dy da linha de base, alinhamento).
CANDIDATES = (
    (10, 4, "start"), (-10, 4, "end"), (10, 20, "start"), (10, -10, "start"),
    (-10, 20, "end"), (-10, -10, "end"),
)  # fmt: skip


def _label_box(x: float, y: float, text: str, anchor: str) -> tuple[float, float, float, float]:
    width = CHAR_W * len(text)
    left = x if anchor == "start" else x - width
    return left, y - LABEL_H, left + width, y + 2


def _overlaps(
    box: tuple[float, float, float, float], other: tuple[float, float, float, float]
) -> bool:
    return box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]


def _place_labels(
    items: list[tuple[float, float, str, bool]], right_edge: float
) -> list[tuple[float, float, str, str]]:
    """Um rótulo por ponto, na primeira posição candidata que não cobre ponto nem outro rótulo.

    O ponto em destaque escolhe primeiro; os demais, de cima para baixo. Sem posição livre, fica
    a primeira que cabe no painel.
    """
    dots = [(x - DOT_R, y - DOT_R, x + DOT_R, y + DOT_R) for x, y, _, _ in items]
    taken: list[tuple[float, float, float, float]] = []
    placed = []
    for x, y, text, _ in sorted(items, key=lambda i: (not i[3], i[1])):
        options = []
        for dx, dy, anchor in CANDIDATES:
            box = _label_box(x + dx, y + dy, text, anchor)
            if box[2] <= right_edge:
                options.append((x + dx, y + dy, anchor, box))
        free = [o for o in options if not any(_overlaps(o[3], b) for b in (*dots, *taken))]
        lx, ly, anchor, box = (free or options)[0]
        taken.append(box)
        placed.append((lx, ly, text, anchor))
    return placed


def _panel(points: Sequence[Point], origin: float, title: str) -> list[str]:
    out = [f'<text class="panel" x="{origin:.1f}" y="{TOP - 14}">{escape(title)}</text>']
    for tick in Y_TICKS:
        y = _y(tick)
        out.append(
            f'<line class="grid" x1="{origin:.1f}" x2="{origin + PANEL_W:.1f}" '
            f'y1="{y:.1f}" y2="{y:.1f}"/>'
        )
        out.append(
            f'<text class="tick" x="{origin - 8:.1f}" y="{y + 4:.1f}" text-anchor="end">'
            f"{tick * 100:.0f}%</text>"
        )
    for tick in (*X_TICKS, *X_MINOR):
        x = _x(tick, origin)
        out.append(
            f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{TOP}" y2="{TOP + PANEL_H}"/>'
        )
        if tick in X_TICKS:
            anchor = "start" if tick == X_MIN else "end" if tick == X_MAX else "middle"
            out.append(
                f'<text class="tick" x="{x:.1f}" y="{TOP + PANEL_H + 18}" '
                f'text-anchor="{anchor}">{_cost_label(tick)}</text>'
            )
    labels = []
    for p in points:
        x, y = _x(p.cost_mean, origin), _y(p.accuracy)
        lo, hi = _y(p.accuracy_ci[0]), _y(p.accuracy_ci[1])
        tip = (
            f"{p.config} ({p.split}, {p.n} leads): acurácia {_pct(p.accuracy)} "
            f"(IC {_pct(p.accuracy_ci[0])}–{_pct(p.accuracy_ci[1])}), "
            f"{_cost_label(p.cost_mean)} por lead"
        )
        final = " final" if p.highlight else ""
        out.append(
            f"<g><title>{escape(tip)}</title>"
            f'<line class="ci{final}" x1="{x:.1f}" x2="{x:.1f}" y1="{lo:.1f}" y2="{hi:.1f}"/>'
            f'<circle class="dot{final}" cx="{x:.1f}" cy="{y:.1f}" r="6"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="transparent"/></g>'
        )
        labels.append((x, y, p.config + (HIGHLIGHT_SUFFIX if p.highlight else ""), p.highlight))
    for lx, ly, text, anchor in _place_labels(labels, origin + PANEL_W):
        cls = "label final" if text.endswith(HIGHLIGHT_SUFFIX) else "label"
        align = ' text-anchor="end"' if anchor == "end" else ""
        # O contorno da cor do fundo vem antes do texto: as barras de IC não cortam o rótulo.
        for kind in ("halo", cls):
            out.append(
                f'<text class="{kind}" x="{lx:.1f}" y="{ly:.1f}"{align}>{escape(text)}</text>'
            )
    return out


def render_svg(points: Sequence[Point]) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="t d">',
        '<title id="t">Custo × acurácia por configuração</title>',
        '<desc id="d">Acurácia contra o gabarito humano (IC 95%) e custo equivalente por lead '
        "(preço de lista da Groq, escala log), nos splits dev e test.</desc>",
        f"<style>{STYLE}</style>",
        f'<rect class="bg" width="{WIDTH}" height="{HEIGHT}" rx="8"/>',
        f'<text class="title" x="{LEFT}" y="30">Custo × acurácia por configuração</text>',
        f'<text class="sub" x="{LEFT}" y="50">Acurácia contra o gabarito humano (barra: IC 95%)'
        " e custo equivalente por lead (preço de lista da Groq, escala log)</text>",
    ]
    for i, (split, title) in enumerate(PANELS):
        origin = LEFT + i * (PANEL_W + GAP)
        out += _panel([p for p in points if p.split == split], origin, title)
    out.append(
        f'<text class="axis" x="{WIDTH / 2:.1f}" y="{HEIGHT - 14}" text-anchor="middle">'
        "Custo equivalente por lead</text>"
    )
    out.append(
        f'<text class="axis" transform="translate(18 {TOP + PANEL_H / 2:.1f}) rotate(-90)" '
        'text-anchor="middle">Acurácia</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--svg", type=Path, default=SVG_PATH)
    args = parser.parse_args(argv)
    points = load_points()
    args.svg.parent.mkdir(parents=True, exist_ok=True)
    args.svg.write_text(render_svg(points), encoding="utf-8")
    print(render_table(points))
    print(f"\ngráfico: {args.svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
