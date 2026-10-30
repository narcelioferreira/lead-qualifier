"""Relatório comparativo entre duas configurações nos **mesmos leads** (T27: `rag` × `mvp`).

Uso:
    uv run python -m evals.compare evals/runs/mvp-v2-test.jsonl evals/runs/rag-test-*.jsonl \\
        --out evals/reports/03-rag.md --title "RAG agêntico × MVP (test)"

O que o relatório mostra:
- as métricas de cada configuração lado a lado (acurácia, kappa, custo, latência, segurança);
- a diferença **pareada** de acurácia (B − A), com IC 95% por bootstrap sobre os leads e o
  teste exato de McNemar nos pares discordantes: com 20 ou 30 leads, a pergunta honesta é se
  a diferença sai do ruído;
- os leads em que o tier mudou, com o rótulo humano;
- na configuração com pesquisa agêntica e próximo passo, as iterações e as citações.

Só usa as linhas de previsão (`PredictionRow`) e o gabarito: não chama nenhuma API.
"""

import argparse
import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.schemas import Tier
from evals.agreement import TIERS
from evals.metrics import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    EvalMetrics,
    Prediction,
    compute_metrics,
    percentile,
)
from evals.run import PredictionRow, attack_ids, load_labels, load_rows, to_predictions


@dataclass(frozen=True)
class Paired:
    """Comparação lead a lead (só leads presentes nas duas rodadas)."""

    n: int
    both_right: int
    only_a: int  # A acertou, B errou
    only_b: int  # B acertou, A errou
    both_wrong: int
    delta: float  # acurácia de B − acurácia de A
    delta_ci: tuple[float, float]
    mcnemar_p: float


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Teste exato de McNemar (binomial bilateral nos pares discordantes)."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail: float = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired(a: Sequence[Prediction], b: Sequence[Prediction]) -> Paired:
    by_id = {p.id: p for p in b}
    pairs = [(p, by_id[p.id]) for p in a if p.id in by_id]
    if not pairs:
        raise ValueError("as duas rodadas não têm leads em comum")
    hits = [(pa.predicted == pa.label, pb.predicted == pb.label) for pa, pb in pairs]
    n = len(hits)

    def delta(sample: Sequence[tuple[bool, bool]]) -> float:
        return (sum(y for _, y in sample) - sum(x for x, _ in sample)) / len(sample)

    # Semente fixa para o IC ser reproduzível; não há uso de segurança aqui.
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311  # nosec B311
    deltas = [delta([hits[rng.randrange(n)] for _ in hits]) for _ in range(BOOTSTRAP_SAMPLES)]
    only_a = sum(x and not y for x, y in hits)
    only_b = sum(y and not x for x, y in hits)
    return Paired(
        n=n,
        both_right=sum(x and y for x, y in hits),
        only_a=only_a,
        only_b=only_b,
        both_wrong=sum(not x and not y for x, y in hits),
        delta=delta(hits),
        delta_ci=(percentile(deltas, 2.5), percentile(deltas, 97.5)),
        mcnemar_p=mcnemar_exact(only_a, only_b),
    )


def _tier(t: Tier | None) -> str:
    return t.value if t else "—"


def _num(value: float | None, fmt: str = ".1%") -> str:
    return "—" if value is None else format(value, fmt)


def _side_by_side(a: EvalMetrics, b: EvalMetrics, names: tuple[str, str]) -> list[str]:
    def kappa_ci(m: EvalMetrics) -> str:
        if m.kappa_linear is None or m.kappa_linear_ci is None:
            return "—"
        low, high = m.kappa_linear_ci
        return f"{_num(m.kappa_linear, '.3f')} ({_num(low, '.3f')} – {_num(high, '.3f')})"

    def acc(m: EvalMetrics) -> str:
        return f"{_num(m.accuracy)} ({_num(m.accuracy_ci[0])} – {_num(m.accuracy_ci[1])})"

    def attacks(m: EvalMetrics) -> str:
        s = m.security
        return f"{s.attacks_detected}/{s.attacks}" if s and s.attacks else "—"

    def false_alarms(m: EvalMetrics) -> str:
        s = m.security
        return f"{s.false_alarms}/{s.legit}" if s else "—"

    rows = [
        ("Acurácia (IC 95%)", acc(a), acc(b)),
        ("Kappa ponderado linear (IC 95%)", kappa_ci(a), kappa_ci(b)),
        ("Kappa simples", _num(a.kappa, ".3f"), _num(b.kappa, ".3f")),
        ("Execuções sem tier", str(a.n - a.completed), str(b.n - b.completed)),
        ("Custo médio por lead (US$)", f"{a.cost_mean:.6f}", f"{b.cost_mean:.6f}"),
        ("Tokens por lead (entrada + saída)",
         f"{(a.input_tokens + a.output_tokens) / a.n:,.0f}",
         f"{(b.input_tokens + b.output_tokens) / b.n:,.0f}"),
        ("Latência p50 / p95 (s)",
         f"{a.latency_p50 / 1000:.1f} / {a.latency_p95 / 1000:.1f}",
         f"{b.latency_p50 / 1000:.1f} / {b.latency_p95 / 1000:.1f}"),
        ("Ataques desqualificados (D)", attacks(a), attacks(b)),
        ("Falso alarme K1 em lead legítimo", false_alarms(a), false_alarms(b)),
    ]  # fmt: skip
    out = [f"| Métrica | {names[0]} | {names[1]} |", "|---|---:|---:|"]
    out += [f"| {label} | {va} | {vb} |" for label, va, vb in rows]
    return out


def _confusion(m: EvalMetrics) -> list[str]:
    out = ["| | A | B | C | D | sem tier |", "|---|---:|---:|---:|---:|---:|"]
    out += [
        f"| **{tier}** | " + " | ".join(str(v) for v in row) + " |"
        for tier, row in zip(TIERS, m.confusion, strict=True)
    ]
    return out


def _rag_section(rows: Sequence[PredictionRow]) -> list[str]:
    agentic = [r for r in rows if r.research_iterations is not None]
    with_step = [r for r in rows if r.next_step_citations is not None]
    if not agentic and not with_step:
        return []
    out = ["", "## Pesquisa agêntica e próximo passo", ""]
    if agentic:
        iterations = Counter(r.research_iterations or 0 for r in agentic)
        dist = " · ".join(f"{k} iteração(ões): {iterations[k]}" for k in sorted(iterations))
        mean = sum(r.research_iterations or 0 for r in agentic) / len(agentic)
        out += [
            f"- **Iterações da pesquisa** ({len(agentic)} execuções): {dist} "
            f"(média {_num(mean, '.2f')}).",
        ]
    if with_step:
        default = sum(bool(r.next_step_default) for r in with_step)
        generated = len(with_step) - default
        cited = Counter(c for r in with_step for c in r.next_step_citations or [])
        cases = sum(
            1 for r in with_step if any(c.startswith("case-") for c in r.next_step_citations or [])
        )
        out += [
            f"- **Próximo passo** ({len(with_step)} execuções com tier): {generated} gerados com "
            f"RAG e {default} no passo padrão do tier (tier D, falha ou sem citação válida).",
            f"- **Citações:** {sum(1 for r in with_step if r.next_step_citations)} de "
            f"{len(with_step)} citam pelo menos um documento; {cases} citam um case; "
            f"{len(cited)} documentos diferentes citados.",
            "- **Mais citados:** "
            + (", ".join(f"`{doc}` ({n})" for doc, n in cited.most_common(5)) or "—")
            + ".",
        ]
    return out


def render_comparison(
    rows_a: Sequence[PredictionRow],
    rows_b: Sequence[PredictionRow],
    labels: dict[str, Tier],
    *,
    title: str,
    attacks: frozenset[str] = frozenset(),
    names: tuple[str, str] | None = None,
) -> str:
    latest_a = list({r.id: r for r in rows_a}.values())
    latest_b = list({r.id: r for r in rows_b}.values())
    common = {r.id for r in latest_a} & {r.id for r in latest_b}
    a_rows = [r for r in latest_a if r.id in common]
    b_rows = [r for r in latest_b if r.id in common]
    pa, pb = to_predictions(a_rows, labels, attacks), to_predictions(b_rows, labels, attacks)
    ma, mb = compute_metrics(pa), compute_metrics(pb)
    name_a, name_b = names or (a_rows[0].config, b_rows[0].config)
    columns = (
        f"{name_a} (`{a_rows[0].prompt_version}`)",
        f"{name_b} (`{b_rows[0].prompt_version}`)",
    )
    diff = paired(pa, pb)
    by_b = {p.id: p for p in pb}
    changed = [(p, by_b[p.id]) for p in pa if p.predicted != by_b[p.id].predicted]

    out = [
        f"# {title}",
        "",
        f"- **Split:** {a_rows[0].split} ({diff.n} leads em comum)",
        f"- **Configurações:** {columns[0]} × {columns[1]}",
        "- **Gabarito:** rotulagem humana (T09), anotador único",
        "",
        "## Lado a lado",
        "",
        *_side_by_side(ma, mb, columns),
        "",
        "## Diferença pareada (mesmos leads)",
        "",
        f"- **Acurácia de {name_b} − {name_a}:** {_num(diff.delta, '+.1%')} "
        f"(IC 95% por bootstrap: {_num(diff.delta_ci[0], '+.1%')} a "
        f"{_num(diff.delta_ci[1], '+.1%')}).",
        f"- **Pares:** {diff.both_right} certos nas duas, {diff.both_wrong} errados nas duas, "
        f"{diff.only_b} só {name_b} acertou, {diff.only_a} só {name_a} acertou.",
        f"- **McNemar exato** (pares discordantes): p = {_num(diff.mcnemar_p, '.3f')}"
        + (
            ". Com essa amostra, a diferença **não** se distingue do ruído."
            if diff.mcnemar_p >= 0.05
            else ". A diferença é significativa a 5%."
        ),
        "",
        f"## Leads em que o tier mudou ({len(changed)})",
        "",
    ]
    if changed:
        out += [f"| Lead | Gabarito | {name_a} | {name_b} | Efeito |", "|---|---|---|---|---|"]
        for p_a, p_b in changed:
            ok_a, ok_b = p_a.predicted == p_a.label, p_b.predicted == p_b.label
            effect = "corrigiu" if ok_b and not ok_a else "errou" if ok_a and not ok_b else "trocou"
            out.append(
                f"| {p_a.id} | {p_a.label.value} | {_tier(p_a.predicted)} | "
                f"{_tier(p_b.predicted)} | {effect} |"
            )
    else:
        out.append("Nenhum.")
    out += ["", f"## Matriz de confusão de {name_b} (linhas = gabarito)", "", *_confusion(mb)]
    out += _rag_section(b_rows)
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path, help="previsões da configuração de referência")
    parser.add_argument("b", type=Path, help="previsões da configuração comparada")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", default="Comparação de configurações")
    parser.add_argument("--names", nargs=2, metavar=("A", "B"), help="nomes das colunas")
    args = parser.parse_args(argv)
    text = render_comparison(
        load_rows(args.a),
        load_rows(args.b),
        load_labels(),
        title=args.title,
        attacks=attack_ids(),
        names=tuple(args.names) if args.names else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
