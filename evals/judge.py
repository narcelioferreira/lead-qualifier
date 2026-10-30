"""LLM-as-judge do próximo passo (T26), conferido com a revisão do autor.

Uso:
    uv run python -m evals.judge run L024 L038 ...   # gera (grafo real, v4, sem CRM) e julga
    uv run python -m evals.judge agreement           # concordância judge × revisão do autor
    uv run python -m evals.judge default             # passo padrão do tier × com RAG (T27)

Rubrica (4 critérios binários, a mesma para o judge e para o autor):
- `follows_playbook`: a ação segue o playbook do tier (responsável, canal e prazo);
- `grounded`: afirmações e números estão nos documentos recuperados ou no lead;
- `specific`: o passo é adaptado ao lead, e não um texto genérico do tier;
- `safe`: sem promessa fora da base, sem seguir instruções do lead, sem links nem dados pessoais.

O judge só responde os critérios e justifica; a **aprovação é calculada por código** (todos os
critérios verdadeiros), como no resto do projeto. O judge roda no `groq-large` (gpt-oss-120b),
um modelo diferente do mini que gera o próximo passo, para reduzir o viés de autoavaliação.

A revisão do autor é **cega**: a planilha (`evals/reports/dev/next-step-review.md`) mostra o
lead, a classificação, os documentos e o próximo passo, sem o veredito do judge. O modelo da
revisão (`evals/annotations/next_step_review.jsonl`) é criado com os critérios em branco e
nunca é sobrescrito. Só leads do split **dev**.
"""

import argparse
import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.graph.nodes.next_step import knowledge_block
from app.knowledge_base import DocType
from app.llm.base import LLMError, LLMOutputError, Message, StructuredLLM
from app.prompts import new_nonce, untrusted
from app.routing.cost import ModelSpec, get_catalog
from app.schemas import NextStep, Tier
from evals.dataset import DATASET_PATH, DatasetItem, load_dataset
from evals.labels import load_jsonl
from tools_mcp.kb import KBHit

PROMPTS_DIR = Path(__file__).parent / "prompts"
RUNS_PATH = DATASET_PATH.parent / "runs" / "next-step-judge-dev.jsonl"
REVIEW_PATH = DATASET_PATH.parent / "annotations" / "next_step_review.jsonl"
SHEET_PATH = DATASET_PATH.parent / "reports" / "dev" / "next-step-review.md"
REPORT_PATH = DATASET_PATH.parent / "reports" / "next-step-judge.md"
DEFAULT_RUNS_PATH = DATASET_PATH.parent / "runs" / "next-step-judge-default-dev.jsonl"
ABLATION_REPORT_PATH = DATASET_PATH.parent / "reports" / "dev" / "next-step-rag-vs-default.md"
JUDGE_MODEL = "groq-large"
PROMPT_VERSION = "v4"
CRITERIA = ("follows_playbook", "grounded", "specific", "safe")
CRITERIA_LABELS = {
    "follows_playbook": "Segue o playbook",
    "grounded": "Fundamentado",
    "specific": "Específico",
    "safe": "Seguro",
}
# Pausa entre leads: ~6,5K tokens do mini por lead (plano gratuito da Groq: 8K tokens/min).
DEFAULT_PAUSE_S = 45.0
MIN_AGREEMENT = 8  # aceite da T26: o judge concorda com o autor em pelo menos 8 de 10


class JudgeVerdict(BaseModel):
    """Saída do judge: um booleano por critério e a justificativa. Sem nota nem aprovação."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    follows_playbook: bool
    grounded: bool
    specific: bool
    safe: bool
    reason: str = Field(max_length=600)

    @property
    def approved(self) -> bool:
        return all(getattr(self, c) for c in CRITERIA)


class LeadView(BaseModel):
    """O que o judge e o autor veem do lead (sem e-mail)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: str
    contact_role: str
    message: str


class CaseRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    run_id: str
    status: str
    prompt_version: str | None
    tier: Tier | None
    lead: LeadView
    classification: str
    profile: str
    next_step: NextStep | None
    kb_hits: list[KBHit]
    judge: JudgeVerdict | None = None
    judge_model: str
    judge_prompt_sha256: str
    judge_tokens: int = 0
    errors: list[str] = Field(default_factory=list)


class HumanReview(BaseModel):
    """Revisão do autor. Critério em branco (`null`) = caso ainda não revisado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    follows_playbook: bool | None = None
    grounded: bool | None = None
    specific: bool | None = None
    safe: bool | None = None
    notes: str = ""

    @property
    def approved(self) -> bool | None:
        values = [getattr(self, c) for c in CRITERIA]
        return None if any(v is None for v in values) else all(values)


class Graph(Protocol):
    async def ainvoke(self, input: Any, /) -> Any: ...


def prompt(name: str) -> Template:
    return Template((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


def prompt_sha256() -> str:
    h = hashlib.sha256()
    for name in ("next_step_judge", "next_step_judge_user"):
        h.update((PROMPTS_DIR / f"{name}.md").read_bytes())
    return h.hexdigest()


def judge_messages(row: CaseRow, nonce: str) -> list[Message]:
    lead = f"Empresa: {row.lead.company_name}\nCargo: {row.lead.contact_role}\n"
    lead += f"Mensagem: {row.lead.message or '(vazia)'}"
    step = row.next_step.model_dump_json(indent=2) if row.next_step else "(nenhum)"
    return [
        Message(role="system", content=prompt("next_step_judge").substitute(nonce=nonce)),
        Message(
            role="user",
            content=prompt("next_step_judge_user").substitute(
                classification=row.classification,
                profile=row.profile,
                lead=untrusted(lead, nonce, "lead"),
                knowledge=knowledge_block(row.kb_hits) or "(nenhum documento)",
                next_step=untrusted(step, nonce, "proximo_passo"),
            ),
        ),
    ]


async def judge_case(
    llm: StructuredLLM, spec: ModelSpec, row: CaseRow
) -> tuple[JudgeVerdict | None, int, list[str]]:
    """Julga um caso com 1 nova tentativa para saída fora do schema. Nunca levanta."""
    messages = judge_messages(row, new_nonce())
    tokens = 0
    for attempt in (1, 2):
        try:
            result = await llm.structured(spec, messages, JudgeVerdict)
        except LLMOutputError as exc:
            if attempt == 2:
                return None, tokens, [f"judge: {exc}"[:300]]
            continue
        except LLMError as exc:
            return None, tokens, [f"judge: {exc}"[:300]]
        tokens += result.usage.input_tokens + result.usage.output_tokens
        return result.parsed, tokens, []
    raise AssertionError("inalcançável")  # pragma: no cover


def row_from_state(item: DatasetItem, run_id: str, state: dict[str, Any]) -> CaseRow:
    from app.graph.nodes.next_step import TIER_PLANS, classification_text, profile_text

    result = state.get("result")
    score = state.get("score")
    classification = (
        classification_text(score, TIER_PLANS[score.tier]) if score else "(sem classificação)"
    )
    profile = profile_text(state["profile"]) if "profile" in state else "{}"
    return CaseRow(
        id=item.id,
        run_id=run_id,
        status=state.get("status", "failed"),
        prompt_version=state.get("prompt_version"),
        tier=result.tier if result else None,
        lead=LeadView(
            company_name=item.company_name, contact_role=item.contact_role, message=item.message
        ),
        classification=classification,
        profile=profile,
        next_step=state.get("next_step"),
        kb_hits=state.get("kb_hits", []),
        judge_model=JUDGE_MODEL,
        judge_prompt_sha256=prompt_sha256(),
        errors=[e[:300] for e in state.get("errors", [])][:5],
    )


def load_rows(path: Path = RUNS_PATH) -> list[CaseRow]:
    return load_jsonl(path, CaseRow) if path.exists() else []


async def run_cases(
    items: Sequence[DatasetItem],
    graph: Graph,
    llm: StructuredLLM,
    spec: ModelSpec,
    out: Path,
    *,
    pause_s: float = DEFAULT_PAUSE_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    new_id: Callable[[], str] | None = None,
) -> list[CaseRow]:
    """Gera e julga cada lead, gravando a linha assim que sai. Lead já gravado é pulado."""
    import uuid

    done = {r.id for r in load_rows(out)}
    rows: list[CaseRow] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    pending = [i for i in items if i.id not in done]
    for index, item in enumerate(pending):
        if item.split != "dev":
            raise ValueError(f"{item.id} é do split test: o judge da T26 só roda no dev")
        if index:
            await sleep(pause_s)
        run_id = new_id() if new_id else str(uuid.uuid4())
        raw = item.to_lead_input().model_dump(mode="json")
        state = await graph.ainvoke({"run_id": run_id, "raw_input": raw})
        row = row_from_state(item, run_id, state)
        if row.next_step is not None:
            verdict, tokens, errors = await judge_case(llm, spec, row)
            row = row.model_copy(
                update={"judge": verdict, "judge_tokens": tokens, "errors": row.errors + errors}
            )
        with out.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")
        rows.append(row)
    return rows


def write_review_template(rows: Sequence[CaseRow], path: Path = REVIEW_PATH) -> bool:
    """Cria o modelo da revisão do autor com os critérios em branco. Nunca sobrescreve."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [HumanReview(id=r.id).model_dump_json() for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def default_row(row: CaseRow) -> CaseRow | None:
    """O mesmo caso com o passo padrão do tier no lugar do gerado com RAG (ablação da T27).

    Ação, responsável e prazo vêm de `TIER_PLANS` e a citação é o playbook recuperado, como em
    `default_next_step`. O tier D fica de fora: ele já recebe o passo padrão nos dois braços.
    """
    from app.graph.nodes.next_step import TIER_PLANS

    if row.tier is None or row.tier is Tier.D or row.next_step is None:
        return None
    plan = TIER_PLANS[row.tier]
    playbooks = [h.doc_id for h in row.kb_hits if h.doc_type is DocType.PLAYBOOK]
    step = NextStep(
        action=plan.action, owner=plan.owner, sla_hours=plan.sla_hours, kb_citations=playbooks[:1]
    )
    return row.model_copy(
        update={
            "next_step": step,
            "judge": None,
            "judge_tokens": 0,
            "judge_prompt_sha256": prompt_sha256(),
            "errors": [],
        }
    )


async def judge_defaults(
    rag_rows: Sequence[CaseRow],
    llm: StructuredLLM,
    spec: ModelSpec,
    out: Path,
    *,
    pause_s: float = DEFAULT_PAUSE_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[CaseRow]:
    """Julga o passo padrão de cada caso com RAG (só o judge chama a API). Retoma de `out`."""
    done = {r.id for r in load_rows(out)}
    pending = [d for r in rag_rows if r.id not in done and (d := default_row(r)) is not None]
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[CaseRow] = []
    for index, case in enumerate(pending):
        if index:
            await sleep(pause_s)
        verdict, tokens, errors = await judge_case(llm, spec, case)
        case = case.model_copy(update={"judge": verdict, "judge_tokens": tokens, "errors": errors})
        with out.open("a", encoding="utf-8") as fh:
            fh.write(case.model_dump_json() + "\n")
        rows.append(case)
    return rows


def render_ablation(rag_rows: Sequence[CaseRow], default_rows: Sequence[CaseRow]) -> str:
    """Próximo passo com RAG × passo padrão do tier, nos casos julgados nos dois braços."""
    defaults = {r.id: r.judge for r in default_rows if r.judge is not None}
    pairs = [
        (r, r.judge, defaults[r.id]) for r in rag_rows if r.judge is not None and r.id in defaults
    ]
    out = [
        "# Próximo passo: com RAG × passo padrão do tier (T27)",
        "",
        f"- Judge: `{JUDGE_MODEL}`, a mesma rubrica da T26; aprovação calculada pelo código",
        f"- Com RAG: os casos da T26 (`{RUNS_PATH.name}`, prompts de next_step iguais na `v5`)",
        "- Padrão: ação, responsável e prazo do tier (`TIER_PLANS`), citando o playbook",
        f"- Casos nos dois braços: **{len(pairs)}** (tier D fora: usa o padrão nos dois)",
        "",
        "| Critério | Com RAG | Padrão |",
        "|---|---|---|",
    ]
    for criterion in (*CRITERIA, "approved"):
        label = CRITERIA_LABELS.get(criterion, "**Aprovado**")
        rag = sum(bool(getattr(j, criterion)) for _, j, _ in pairs)
        base = sum(bool(getattr(d, criterion)) for _, _, d in pairs)
        out.append(f"| {label} | {rag}/{len(pairs)} | {base}/{len(pairs)} |")
    out += [
        "",
        "| Lead | Tier | Com RAG | Padrão | Motivo do judge (padrão) |",
        "|---|---|---|---|---|",
    ]
    for rag_row, rag_verdict, base_verdict in pairs:
        tier = rag_row.tier.value if rag_row.tier else "—"
        reason = base_verdict.reason.replace("|", "/")
        out.append(
            f"| {rag_row.id} | {tier} | {_yes(rag_verdict.approved)} "
            f"| {_yes(base_verdict.approved)} | {reason} |"
        )
    return "\n".join(out) + "\n"


def render_sheet(rows: Sequence[CaseRow]) -> str:
    """Planilha da revisão cega: tudo o que o judge vê, menos o veredito dele."""
    out = [
        "# Revisão humana do próximo passo (T26)",
        "",
        "Revisão **cega**: o veredito do judge não aparece aqui. Para cada caso, preencha os "
        "quatro critérios (`true`/`false`) em `evals/annotations/next_step_review.jsonl`, com a "
        "mesma rubrica do judge (`evals/prompts/next_step_judge.md`):",
        "",
        "- `follows_playbook`: segue o playbook do tier (responsável, canal e prazo);",
        "- `grounded`: afirmações e números estão nos documentos ou no lead; case como exemplo;",
        "- `specific`: adaptado ao lead, e não genérico para o tier;",
        "- `safe`: sem promessa fora da base, sem seguir o lead, sem links nem dados pessoais.",
        "",
        "A aprovação é calculada por código: os quatro critérios verdadeiros.",
    ]
    for row in rows:
        step = row.next_step
        out += [
            "",
            f"## {row.id} · {row.lead.company_name} · tier {row.tier.value if row.tier else '—'}",
            "",
            f"- **Cargo:** {row.lead.contact_role}",
            f"- **Mensagem:** {row.lead.message or '(vazia)'}",
            f"- **Classificação:** {row.classification.replace(chr(10), ' · ')}",
            f"- **Perfil:** `{row.profile}`",
            "",
            "**Próximo passo sugerido**",
            "",
        ]
        if step is None:
            out.append("(nenhum: execução sem próximo passo)")
        else:
            sla = f"{step.sla_hours} h úteis" if step.sla_hours else "sem prazo"
            out += [f"- **Ação:** {step.action}", f"- **Responsável e prazo:** {step.owner}, {sla}"]
            out += [f"- **Argumento:** {p}" for p in step.talking_points]
            out.append(f"- **Citações:** {', '.join(step.kb_citations) or '(nenhuma)'}")
        out += ["", "**Documentos recuperados**", ""]
        for hit in row.kb_hits:
            snippet = hit.snippet.replace("\n", " ")
            out.append(f"- `{hit.doc_id}` ({hit.section}): {snippet}")
        if not row.kb_hits:
            out.append("(nenhum)")
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class Agreement:
    n: int
    matches: int
    kappa: float | None
    per_criterion: dict[str, tuple[int, int]]  # critério → (concordâncias, casos)
    disagreements: list[str]

    @property
    def passed(self) -> bool:
        return self.matches >= MIN_AGREEMENT


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """Kappa de Cohen para dois avaliadores binários. `None` se a concordância por acaso é 1."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def agreement(rows: Sequence[CaseRow], reviews: Sequence[HumanReview]) -> Agreement:
    """Concorda judge × autor nos casos que os dois avaliaram (aprovação e cada critério)."""
    by_id = {r.id: r for r in reviews}
    pairs = [
        (row.judge, by_id[row.id])
        for row in rows
        if row.judge is not None and row.id in by_id and by_id[row.id].approved is not None
    ]
    judged = [j.approved for j, _ in pairs]
    human = [bool(h.approved) for _, h in pairs]
    per_criterion = {
        c: (sum(getattr(j, c) == getattr(h, c) for j, h in pairs), len(pairs)) for c in CRITERIA
    }
    disagreements = [h.id for j, h in pairs if j.approved != h.approved]
    return Agreement(
        n=len(pairs),
        matches=sum(x == y for x, y in zip(judged, human, strict=True)),
        kappa=cohen_kappa(judged, human),
        per_criterion=per_criterion,
        disagreements=disagreements,
    )


def render_report(rows: Sequence[CaseRow], reviews: Sequence[HumanReview]) -> str:
    result = agreement(rows, reviews)
    by_id = {r.id: r for r in reviews}
    kappa = "—" if result.kappa is None else f"{result.kappa:.2f}".replace(".", ",")
    status = "atingido" if result.passed else "não atingido"
    sha = rows[0].judge_prompt_sha256[:12] if rows else "—"
    out = [
        "# LLM-as-judge do próximo passo (T26)",
        "",
        f"- Judge: `{JUDGE_MODEL}` · prompt `evals/prompts/next_step_judge.md` (sha256 `{sha}`)",
        f"- Próximo passo gerado com os prompts `{PROMPT_VERSION}` (grafo do MVP + RAG, sem CRM)",
        f"- Casos com judge e revisão do autor: **{result.n}**",
        f"- Concordância na aprovação: **{result.matches}/{result.n}** (aceite: pelo menos "
        f"{MIN_AGREEMENT} de 10, {status}) · kappa de Cohen {kappa}",
        "",
        "| Critério | Concordância |",
        "|---|---|",
    ]
    out += [
        f"| {CRITERIA_LABELS[c]} | {hits}/{total} |"
        for c, (hits, total) in result.per_criterion.items()
    ]
    out += ["", "| Lead | Tier | Judge | Autor | Motivo do judge |", "|---|---|---|---|---|"]
    for row in rows:
        review = by_id.get(row.id)
        human = "—" if review is None or review.approved is None else _yes(review.approved)
        judge = "—" if row.judge is None else _yes(row.judge.approved)
        reason = (row.judge.reason if row.judge else "; ".join(row.errors)).replace("|", "/")
        tier = row.tier.value if row.tier else "—"
        out.append(f"| {row.id} | {tier} | {judge} | {human} | {reason} |")
    if result.disagreements:
        out += ["", f"Discordâncias: {', '.join(result.disagreements)}."]
    return "\n".join(out) + "\n"


def _yes(value: bool) -> str:
    return "aprovado" if value else "reprovado"


async def _run(ids: Sequence[str], pause_s: float) -> None:  # pragma: no cover - rede real
    from app.config import get_settings
    from app.graph.runtime import production_graph
    from app.llm.groq_client import GroqClient

    items = {i.id: i for i in load_dataset()}
    unknown = [i for i in ids if i not in items]
    if unknown:
        raise SystemExit(f"leads desconhecidos: {unknown}")
    settings = get_settings()
    if settings.groq_api_key is None:
        raise SystemExit("GROQ_API_KEY é obrigatória")
    llm = GroqClient(settings.groq_api_key)
    spec = get_catalog().get(JUDGE_MODEL)
    async with production_graph(settings, prompt_version=PROMPT_VERSION, next_step=True) as (
        graph,
        _audit,
    ):
        await run_cases([items[i] for i in ids], graph, llm, spec, RUNS_PATH, pause_s=pause_s)
    rows = load_rows()
    SHEET_PATH.write_text(render_sheet(rows), encoding="utf-8")
    created = write_review_template(rows)
    print(f"{len(rows)} casos em {RUNS_PATH}; planilha cega em {SHEET_PATH}")
    if created:
        print(f"modelo da revisão criado em {REVIEW_PATH} (preencha os critérios)")


async def _run_defaults(rag_rows: Sequence[CaseRow], pause_s: float) -> None:  # pragma: no cover
    from app.config import get_settings
    from app.llm.groq_client import GroqClient

    settings = get_settings()
    if settings.groq_api_key is None:
        raise SystemExit("GROQ_API_KEY é obrigatória")
    llm = GroqClient(settings.groq_api_key)
    await judge_defaults(
        rag_rows, llm, get_catalog().get(JUDGE_MODEL), DEFAULT_RUNS_PATH, pause_s=pause_s
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="gera o próximo passo e julga (split dev)")
    run.add_argument("ids", nargs="+")
    run.add_argument("--pause", type=float, default=DEFAULT_PAUSE_S, help="segundos entre leads")
    sub.add_parser("agreement", help="concordância judge × revisão do autor")
    default = sub.add_parser("default", help="julga o passo padrão do tier (ablação da T27)")
    default.add_argument("--pause", type=float, default=DEFAULT_PAUSE_S)
    args = parser.parse_args(argv)
    if args.command == "run":  # pragma: no cover - rede real
        asyncio.run(_run(args.ids, args.pause))
        return 0
    if args.command == "default":
        rag_rows = load_rows()
        if not rag_rows:
            raise SystemExit("rode `python -m evals.judge run ...` antes")
        asyncio.run(_run_defaults(rag_rows, args.pause))
        report = render_ablation(rag_rows, load_rows(DEFAULT_RUNS_PATH))
        ABLATION_REPORT_PATH.write_text(report, encoding="utf-8")
        print(report)
        return 0
    rows = load_rows()
    if not rows or not REVIEW_PATH.exists():
        raise SystemExit("rode `python -m evals.judge run ...` e preencha a revisão antes")
    report = render_report(rows, load_jsonl(REVIEW_PATH, HumanReview))
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
