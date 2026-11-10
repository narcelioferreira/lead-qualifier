"""Custo × acurácia (T30): pontos a partir das previsões gravadas, tabela e SVG, sem API."""

import shutil
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from evals import cost_chart
from evals.cost_chart import ConfigRuns, Point

RUNS = Path("evals/runs")


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    for stem in ("mvp-v2-sec-dev", "mvp-v2-test", "rag-v5-test"):
        shutil.copy(RUNS / f"{stem}.jsonl", tmp_path / f"{stem}.jsonl")
    return tmp_path


CONFIGS = (
    ConfigRuns("mvp", "x", "mvp-v2-sec-dev", "mvp-v2-test"),
    ConfigRuns("rag", "x", "rag-v5-dev-ausente", "rag-v5-test"),
)


def test_points_come_from_the_saved_runs_and_skip_missing_files(runs: Path) -> None:
    points = cost_chart.load_points(CONFIGS, runs)
    assert [(p.config, p.split, p.n) for p in points] == [
        ("mvp", "dev", 20), ("mvp", "test", 30), ("rag", "test", 30),
    ]  # fmt: skip
    mvp_test = points[1]
    assert mvp_test.accuracy == pytest.approx(0.6)  # 02-mvp.md
    assert mvp_test.cost_mean == pytest.approx(0.000356, abs=1e-6)


def test_table_uses_brazilian_number_format(runs: Path) -> None:
    table = cost_chart.render_table(cost_chart.load_points(CONFIGS, runs))
    assert "| `mvp` | test (30) | 60,0% (43,3%–76,7%) | 0,560 | US$ 0,000356 |" in table


def point(config: str, split: str, cost: float, acc: float) -> Point:
    return Point(config, split, 30, acc, (acc - 0.1, acc + 0.1), 0.5, cost, 1000.0, 2000.0)


def test_svg_is_valid_has_both_panels_labels_and_tooltips() -> None:
    points = [
        point("baseline", "test", 1.5e-4, 0.53),
        point("rag", "test", 7.6e-4, 0.667),
        point("routing", "test", 9.0e-4, 0.66),  # perto do rag: o rótulo desce
        point("large_only", "test", 0.0095, 0.7),  # na borda: rótulo à esquerda
        point("mvp", "dev", 3.6e-4, 0.95),
    ]
    svg = cost_chart.render_svg(points)
    root = ET.fromstring(svg)  # noqa: S314 - XML gerado pelo próprio código, não por terceiros
    ns = "{http://www.w3.org/2000/svg}"
    texts = [t.text for t in root.iter(f"{ns}text")]
    assert "dev: 20 leads, usado no ajuste" in texts and "test: 30 leads, rodada única" in texts
    assert {"baseline", "rag", "routing", "large_only", "mvp"} <= set(texts)
    tips = [t.text or "" for t in root.iter(f"{ns}title")]
    assert any(t.startswith("rag (test, 30 leads): acurácia 66,7%") for t in tips)
    assert "prefers-color-scheme: dark" in svg
    labels = {t.text: t for t in root.iter(f"{ns}text") if t.get("class") == "label"}
    assert labels["large_only"].get("text-anchor") == "end"
    boxes = [
        cost_chart._label_box(
            float(t.get("x", 0)), float(t.get("y", 0)), t.text or "", t.get("text-anchor", "start")
        )
        for t in labels.values()
    ]
    assert not any(  # rag e routing estão colados: os rótulos não podem se cobrir
        cost_chart._overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :]
    )


def test_labels_avoid_dots_and_the_highlight_chooses_first() -> None:
    items = [(100.0, 100.0, "mvp", False), (115.0, 100.0, "api (entregue)", True)]
    placed = {text: (x, anchor) for x, _, text, anchor in cost_chart._place_labels(items, 400)}
    assert placed["api (entregue)"] == (125.0, "start")  # destaque fica à direita
    assert placed["mvp"] == (90.0, "end")  # à direita cobriria o ponto da api


def test_scales_are_log_on_cost_and_clamped() -> None:
    origin = cost_chart.LEFT
    assert cost_chart._x(1e-4, origin) == pytest.approx(origin)
    assert cost_chart._x(1e-3, origin) == pytest.approx(origin + cost_chart.PANEL_W / 2)
    assert cost_chart._x(1.0, origin) == pytest.approx(origin + cost_chart.PANEL_W)
    assert cost_chart._y(1.0) == cost_chart.TOP
    assert cost_chart._y(0.0) == cost_chart.TOP + cost_chart.PANEL_H
    assert cost_chart._cost_label(1e-3) == "US$ 0,001"


def test_main_writes_the_svg(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "chart.svg"
    assert cost_chart.main(["--svg", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<svg")
    assert "| Configuração | Split |" in capsys.readouterr().out


def test_delivered_config_is_highlighted_with_its_own_class_and_label() -> None:
    final = point("api", "test", 4.3e-4, 0.6)
    svg = cost_chart.render_svg([point("mvp", "test", 3.6e-4, 0.6), replace(final, highlight=True)])
    root = ET.fromstring(svg)  # noqa: S314 - XML gerado pelo próprio código, não por terceiros
    ns = "{http://www.w3.org/2000/svg}"
    labels = {
        t.text: t.get("class") for t in root.iter(f"{ns}text") if "label" in (t.get("class") or "")
    }
    assert labels == {"mvp": "label", "api (entregue)": "label final"}
    dots = [c.get("class") for c in root.iter(f"{ns}circle") if c.get("class")]
    assert sorted(dots) == ["dot", "dot final"]


def test_default_configs_include_the_delivered_api_config() -> None:
    api = [c for c in cost_chart.CONFIGS if c.highlight]
    assert [(c.name, c.dev, c.test) for c in api] == [("api", "api-v6-dev", "api-v6-test")]
