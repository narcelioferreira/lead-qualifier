"""Pesquisa agêntica (T25): planeja, busca, avalia a suficiência e reformula, em loop limitado.

Cada passagem pelo nó `agentic_research` é uma iteração:
1. **busca**: na 1ª, a pesquisa do MVP (mensagem, site declarado e busca pelo nome); nas
   seguintes, a consulta proposta na iteração anterior;
2. **avaliação** (estilo Corrective RAG): o mini diz quais fatos ainda faltam (`sector`,
   `size`, `region`) e propõe a próxima consulta. **O código decide** se o loop continua.

Limites (OWASP ASI08 / ASI10): no máximo 3 iterações, um teto de tokens só para a pesquisa e o
orçamento da execução inteira (`RunBudget`). Atingido qualquer um, a pesquisa segue com o que
tem, e o que faltar vira `unknown` na extração. O roteador confere um teto fixo de iterações
independente do nó, então nem um nó com defeito gera loop infinito.

Fontes: o site só é lido no domínio **declarado pelo lead** (na 1ª iteração), e as consultas
seguintes vão só para a busca na web. O agente não escolhe um site novo a partir de páginas de
terceiros (um resultado de busca envenenado não pode apontar a leitura), e a base de
conhecimento fica para o próximo passo (T26): seus cases fictícios têm porte e UF que a
extração poderia atribuir ao lead por engano.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.audit.repository import StepRecord
from app.graph.builder import GraphNodes, Node
from app.graph.nodes.core import HARD_MAX_ITERATIONS
from app.graph.nodes.mvp import (
    MvpDeps,
    RunBudget,
    _ask,
    _lead_text,
    evidence_ids,
    initial_query,
    initial_research,
    injection_hits,
    make_nodes,
    search_evidence,
)
from app.graph.state import QualificationState
from app.llm.base import Message
from app.prompts import new_nonce, untrusted
from app.schemas import Evidence, sanitize_text
from tools_mcp.base import ToolError
from tools_mcp.search import MAX_QUERY_CHARS, MIN_QUERY_CHARS

NODE = "agentic_research"
PLAN_SNIPPET_CHARS = 300  # o planejador vê trechos curtos: o plano gratuito tem 8K tokens/min
MAX_PLAN_QUERY_CHARS = 200
_FORBIDDEN_IN_QUERY = re.compile(r"https?://|www\.|@|<|>", re.IGNORECASE)
_SPACES = re.compile(r"\s+")

Fact = Literal["sector", "size", "region"]


class ResearchPlan(BaseModel):
    """Saída do planejador: o que falta e a próxima consulta. Quem decide o loop é o código."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    missing: list[Fact] = Field(max_length=3)
    next_query: str | None = Field(default=None, max_length=MAX_PLAN_QUERY_CHARS)
    reason: str = Field(max_length=300)


@dataclass(frozen=True)
class ResearchLimits:
    max_iterations: int = HARD_MAX_ITERATIONS
    # Tokens das chamadas do planejador (o custo real no plano gratuito é o limite de tokens).
    max_tokens: int = 6_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_iterations <= HARD_MAX_ITERATIONS:
            raise ValueError(f"max_iterations deve estar entre 1 e {HARD_MAX_ITERATIONS}")
        if self.max_tokens < 0:
            raise ValueError("max_tokens não pode ser negativo")


def clean_query(text: str | None, tried: Sequence[str]) -> str | None:
    """Consulta proposta pelo LLM, validada pelo código. `None` = não há consulta utilizável.

    O LLM leu conteúdo não confiável, então a consulta é limitada: sem links, e-mails ou tags,
    tamanho dentro do limite da ferramenta e sem repetir uma consulta já feita.
    """
    if not text:
        return None
    query = _SPACES.sub(" ", sanitize_text(text)).strip()
    if not MIN_QUERY_CHARS <= len(query) <= min(MAX_QUERY_CHARS, MAX_PLAN_QUERY_CHARS):
        return None
    if _FORBIDDEN_IN_QUERY.search(query):
        return None
    if query.casefold() in {t.casefold() for t in tried}:
        return None
    return query


def _plan_evidence(evidence: Sequence[Evidence], nonce: str) -> str:
    blocks = []
    for eid, ev in zip(evidence_ids(evidence), evidence, strict=True):
        header = f"[{eid}] {ev.source_type.value}" + (f" {ev.source_url}" if ev.source_url else "")
        blocks.append(f"{header}\n{untrusted(ev.snippet[:PLAN_SNIPPET_CHARS], nonce, eid)}")
    return "\n\n".join(blocks) or "(nenhuma evidência)"


def _research_tokens(steps: Sequence[StepRecord]) -> int:
    return sum(
        s.usage.input_tokens + s.usage.output_tokens
        for s in steps
        if s.node == NODE and s.model_key
    )


def make_agentic_research(deps: MvpDeps, limits: ResearchLimits | None = None) -> Node:
    limits = limits or ResearchLimits()

    async def agentic_research(state: QualificationState) -> dict[str, Any]:
        lead = state["lead"]
        iteration = state.get("research_iterations", 0) + 1
        tried = list(state.get("research_queries", []))
        known = {str(e.source_url) for e in state.get("evidence", []) if e.source_url}
        errors: list[str] = []

        if iteration == 1:
            new_evidence, errors = await initial_research(deps, lead)
            query = initial_query(lead)
        else:
            query = state.get("research_next") or ""
            try:
                found = await deps.search.search(query)
            except ToolError as exc:
                new_evidence, errors = [], [f"busca: {exc}"]
            else:
                # Uma página já coletada não entra de novo (a extração veria duas vezes).
                new_evidence = [e for e in search_evidence(found) if str(e.source_url) not in known]
        tried.append(query)
        evidence = [*state.get("evidence", []), *new_evidence]

        plan_steps: list[StepRecord] = []
        plan: ResearchPlan | None = None
        steps_so_far = state.get("steps", [])
        if iteration >= limits.max_iterations:
            stop = "limite de iterações"
        elif _research_tokens(steps_so_far) >= limits.max_tokens:
            stop = "teto de tokens da pesquisa"
        elif injection_hits(lead, evidence, evidence_ids(evidence)):
            # Injeção conhecida: o texto não vai a nenhum LLM (o normalize aplica a K1).
            stop = "injeção detectada por regra: planejador não chamado"
        else:
            nonce = new_nonce()
            messages = [
                Message(
                    role="system", content=deps.prompt("research_plan").substitute(nonce=nonce)
                ),
                Message(
                    role="user",
                    content=deps.prompt("research_plan_user").substitute(
                        lead=untrusted(_lead_text(lead), nonce, "lead"),
                        queries="\n".join(f"- {q}" for q in tried),
                        evidence=_plan_evidence(evidence, nonce),
                    ),
                ),
            ]
            result, plan_steps, plan_errors = await _ask(deps, state, NODE, messages, ResearchPlan)
            errors += plan_errors
            if result is None:
                stop = "planejador indisponível: segue com as evidências atuais"
            else:
                plan = result.parsed
                plan_steps.append(StepRecord.from_llm(NODE, result, route_reason="avaliação"))
                stop = "evidência suficiente" if not plan.missing else ""

        next_query = None
        if not stop and plan is not None:
            next_query = clean_query(plan.next_query, tried)
            stop = "" if next_query else "sem consulta nova utilizável"

        summary = StepRecord(
            node=NODE,
            route_reason=stop or "evidência insuficiente: nova consulta",
            output={
                "iteration": iteration,
                "query": query,
                "new_evidence": len(new_evidence),
                "missing": list(plan.missing) if plan else None,
                "next_query": next_query,
                "errors": len(errors),
            },
            sources=[str(e.source_url) for e in new_evidence if e.source_url],
        )
        return {
            "evidence": new_evidence,
            "research_iterations": iteration,
            "research_queries": tried,
            "research_next": next_query,
            "errors": errors,
            "steps": [*plan_steps, summary],
        }

    return agentic_research


# O loop acrescenta até 2 chamadas do planejador (4 com nova tentativa) às 2 do MVP (4).
AGENTIC_BUDGET = RunBudget(max_llm_calls=10, max_tokens=40_000)


def make_agentic_nodes(deps: MvpDeps, limits: ResearchLimits | None = None) -> GraphNodes:
    """Nós do MVP com o `research` trocado pelo `agentic_research`. Use com `agentic=True`."""
    try:
        deps.prompt("research_plan")
        deps.prompt("research_plan_user")
    except FileNotFoundError:
        raise ValueError(
            f"a versão de prompt {deps.prompt_version} não tem o planejador da pesquisa (use v3)"
        ) from None
    return replace(make_nodes(deps), research=make_agentic_research(deps, limits))
