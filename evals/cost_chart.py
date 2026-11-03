"""Custo × acurácia de todas as configurações (T30): tabela em Markdown e gráfico em SVG.

Lê as previsões gravadas de cada configuração (dev e test) e o gabarito humano. Não chama API.
O SVG não tem dependência externa (nada de matplotlib): é texto, versionado ao lado do relatório,
com tema claro e escuro (`prefers-color-scheme`) e um tooltip por ponto (`<title>`).

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


# Ordem = ordem das ablações da arquitetura (seção 11).
CONFIGS: tuple[ConfigRuns, ...] = (
    ConfigRuns("baseline", "prompt único, o LLM decide o tier", "baseline-dev", "baseline-test"),
    ConfigRuns("mvp", "ontologia + score em código", "mvp-v2-sec-dev", "mvp-v2-test"),
    ConfigRuns("rag", "+ pesquisa agêntica e próximo passo", "rag-v5-dev", "rag-v5-test"),
    ConfigRuns("routing", "+ guardrail e roteamento", "routing-v6-dev", "routing-v6-test"),
    ConfigRuns("large_only", "tudo no modelo maior", "large_only-v6-dev", "large_only-v6-test"),
)
SVG_PATH = REPORTS_DIR / "04-routing-custo-acuracia.svg"


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
LABEL_GAP = 15  # distância vertical mínima entre rótulos
PANELS = (("dev", "dev: 20 leads, usado no ajuste"), ("test", "test: 30 leads, rodada única"))

STYLE = """
.viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --grid:#e6e5e1; --mark:#2a78d6; }
@media (prefers-color-scheme: dark) {
  .viz { --surface:#1a1a19; --ink:#f0efec; --ink-2:#c3c2b7; --grid:#33322f; --mark:#3987e5; }
}
.bg { fill: var(--surface); }
.title { fill: var(--ink); font: 600 16px system-ui, sans-serif; }
.panel { fill: var(--ink); font: 600 13px system-ui, sans-serif; }
.sub, .tick, .axis { fill: var(--ink-2); font: 12px system-ui, sans-serif; }
.label { fill: var(--ink); font: 600 12px system-ui, sans-serif; }
.grid { stroke: var(--grid); stroke-width: 1; }
.ci { stroke: var(--mark); stroke-width: 2; stroke-linecap: round; opacity: .45; }
.dot { fill: var(--mark); stroke: var(--surface); stroke-width: 2; }
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


def _place_labels(items: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Rótulos à direita do ponto (à esquerda perto da borda); desloca o que colidiria."""
    placed: list[tuple[float, float, str]] = []
    for x, y, text in sorted(items, key=lambda i: i[1]):
        ly = y + 4
        for px, py, _ in placed:
            if abs(px - x) < 90 and abs(py - ly) < LABEL_GAP:
                ly = py + LABEL_GAP
        placed.append((x, ly, text))
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
        out.append(
            f"<g><title>{escape(tip)}</title>"
            f'<line class="ci" x1="{x:.1f}" x2="{x:.1f}" y1="{lo:.1f}" y2="{hi:.1f}"/>'
            f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="6"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="transparent"/></g>'
        )
        labels.append((x, y, p.config))
    for x, y, text in _place_labels(labels):
        if x + 10 + 7 * len(text) > origin + PANEL_W:
            out.append(
                f'<text class="label" x="{x - 10:.1f}" y="{y:.1f}" text-anchor="end">'
                f"{escape(text)}</text>"
            )
        else:
            out.append(f'<text class="label" x="{x + 10:.1f}" y="{y:.1f}">{escape(text)}</text>')
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
