"""Guardrail de entrada (T28): barra injeção e spam antes da pesquisa e da extração.

Ordem das camadas:

1. **Regras determinísticas** (`app/security/injection.py`) no nome, no cargo e na mensagem:
   padrão conhecido bloqueia sem chamar modelo nenhum.
2. **Mini (Groq)** responde três perguntas (`GuardrailVerdict`): injeção, spam e fora de escopo.
   O lead vai delimitado no prompt (`<dados_{nonce}>`), e a saída é validada pelo schema.
3. **SLM local (Ollama) de reserva** quando o mini está fora do ar ou devolve saída inválida
   duas vezes.

O plano era o inverso (SLM primeiro, mini de reserva). O benchmark da T28
(`evals/reports/guardrail-bench.md`, ADR 0006) mostrou que nenhum SLM de 1B a 4B atinge a meta
em CPU: o melhor pegou 64% das injeções, contra 92% do mini, sem bloquear legítimos. O SLM fica
como reserva porque ainda é melhor que nenhum filtro quando a Groq falha só nesta chamada.

Injeção ou spam viram a flag da ontologia (`LeadFlag`), e o código aplica a K1: o lead vai
direto para o `compute_score`, sem pesquisa nem extração. **Fora de escopo só é registrado**:
estudante, candidato, fornecedor e pessoa física já têm regras próprias (K3, K4 e K5), decididas
a partir das evidências; deixar o guardrail desqualificar por isso tiraria a decisão da rubrica.

Se o mini e o SLM falharem, o lead **segue** para a pesquisa (fail open), com o erro registrado:
as regras e a flag de injeção do `normalize` continuam valendo depois.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from string import Template
from typing import Any

from app.audit.repository import StepRecord
from app.graph.builder import GraphNodes, Node
from app.graph.nodes.extraction import confidence
from app.graph.nodes.mvp import MvpDeps, RunBudget, _ask, _lead_text
from app.graph.state import QualificationState
from app.llm.base import Message, StructuredLLM
from app.ontology.models import LeadFlag, LeadProfile
from app.prompts import new_nonce, untrusted
from app.schemas import LeadInput, sanitize_text
from app.security.guardrail import REASON_CHARS, GuardrailVerdict
from app.security.injection import scan_sources

NODE = "guardrail"
SLM_KEY = "ollama-slm"
PRIMARY = "mini"
FALLBACK = "fallback: mini indisponível ou saída inválida, SLM local"
# Até 2 chamadas ao mini e 2 ao SLM (cada um com 1 nova tentativa), com prompts curtos.
GUARDRAIL_CALLS = 4
GUARDRAIL_TOKENS = 8_000


@dataclass(frozen=True)
class GuardrailCheck:
    """Resultado de uma checagem: veredito (ou `None` se tudo falhou), passos e erros."""

    verdict: GuardrailVerdict | None
    rule_hits: list[str]
    steps: list[StepRecord]
    errors: list[str]

    @property
    def flags(self) -> frozenset[LeadFlag]:
        if self.rule_hits:
            return frozenset({LeadFlag.INJECTION})
        return self.verdict.flags if self.verdict else frozenset()


def guardrail_messages(lead: LeadInput, prompt: Template, prompt_user: Template) -> list[Message]:
    # O system prompt não leva o nonce: fixo, ele fica no cache de prefixo do Ollama (em CPU, a
    # leitura do prompt é a maior parte da latência). O nonce vai na mensagem do usuário.
    nonce = new_nonce()
    return [
        Message(role="system", content=prompt.substitute()),
        Message(
            role="user",
            content=prompt_user.substitute(
                nonce=nonce, lead=untrusted(_lead_text(lead), nonce, "lead")
            ),
        ),
    ]


def rule_hits(lead: LeadInput) -> list[str]:
    """Padrões conhecidos no que o lead escreveu (nome, cargo e mensagem)."""
    text = f"{lead.company_name}\n{lead.contact_role}\n{lead.message}"
    return [f"{h.source}:{h.family}" for h in scan_sources([("lead", text)])]


async def check(
    deps: MvpDeps, slm: StructuredLLM, state: QualificationState, lead: LeadInput
) -> GuardrailCheck:
    """Regras → mini → SLM. Nunca levanta; o orçamento da execução vale para as chamadas."""
    hits = rule_hits(lead)
    if hits:
        step = StepRecord(
            node=NODE,
            route_reason="injeção detectada por regra: nenhum modelo chamado",
            output={"injection_hits": hits},
        )
        return GuardrailCheck(None, hits, [step], [])
    messages = guardrail_messages(lead, deps.prompt("guardrail"), deps.prompt("guardrail_user"))
    steps: list[StepRecord] = []
    errors: list[str] = []
    routes: Sequence[tuple[MvpDeps, str]] = (
        (deps, PRIMARY),
        (replace(deps, llm=slm, model_key=SLM_KEY), FALLBACK),
    )
    for route_deps, reason in routes:
        # O state "visto" pelo orçamento inclui os passos desta checagem.
        seen: QualificationState = {**state, "steps": [*state.get("steps", []), *steps]}
        result, tried, failed = await _ask(route_deps, seen, NODE, messages, GuardrailVerdict)
        steps += tried
        errors += failed
        if result is not None:
            verdict = result.parsed.model_copy(
                update={"reason": sanitize_text(result.parsed.reason)[:REASON_CHARS]}
            )
            steps.append(
                StepRecord.from_llm(NODE, replace(result, parsed=verdict), route_reason=reason)
            )
            return GuardrailCheck(verdict, [], steps, errors)
    return GuardrailCheck(None, [], steps, [*errors, f"{NODE}: mini e SLM de reserva falharam"])


def blocked_update(result: GuardrailCheck, prompt_version: str) -> dict[str, Any]:
    """State de um lead barrado: só a flag na ontologia; o código aplica a K1 e dá o tier D."""
    profile = LeadProfile(flags=result.flags)
    kinds = sorted(f.value for f in result.flags)
    origin = "regra determinística" if result.rule_hits else "guardrail"
    return {
        "prompt_version": prompt_version,
        "guardrail_blocked": True,
        "profile": profile,
        "confidence": confidence(profile),
        "injection_hits": result.rule_hits,
        "research_iterations": 0,
        "rationale": (
            f"Lead desqualificado na entrada por {origin}: {', '.join(kinds)}. "
            "Não houve pesquisa nem extração."
        ),
    }


def make_guardrail(deps: MvpDeps, slm: StructuredLLM) -> Node:
    async def guardrail(state: QualificationState) -> dict[str, Any]:
        result = await check(deps, slm, state, state["lead"])
        update: dict[str, Any] = {"steps": result.steps, "errors": result.errors}
        if result.verdict is not None:
            update["guardrail"] = result.verdict
        if result.flags:
            update |= blocked_update(result, deps.prompt_version)
        return update

    return guardrail


def guardrail_budget(budget: RunBudget) -> RunBudget:
    """Orçamento da execução com a folga do guardrail somada."""
    return replace(
        budget,
        max_llm_calls=budget.max_llm_calls + GUARDRAIL_CALLS,
        max_tokens=budget.max_tokens + GUARDRAIL_TOKENS,
    )


def with_guardrail(nodes: GraphNodes, deps: MvpDeps, slm: StructuredLLM) -> GraphNodes:
    """Acrescenta o guardrail real. Use com `build_graph(..., guardrail=True)` e prompts `v6`.

    `deps.budget` já deve incluir a folga (`guardrail_budget`), aplicada antes de montar os
    outros nós, que conferem o mesmo orçamento.
    """
    try:
        deps.prompt("guardrail")
        deps.prompt("guardrail_user")
    except FileNotFoundError:
        raise ValueError(
            f"a versão de prompt {deps.prompt_version} não tem o guardrail (use v6)"
        ) from None
    return replace(nodes, guardrail=make_guardrail(deps, slm))
