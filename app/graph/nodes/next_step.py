"""Próximo passo comercial com RAG (T26): playbook do tier e cases do setor, sempre citados.

Divisão do trabalho (o LLM redige; o código decide):
- o **código** recupera os documentos na base (filtro por tipo, tier e setor da ontologia), fixa
  o responsável e o prazo pelo tier (`docs/01-contexto-negocio.md`) e confere a saída;
- o **mini** escreve a ação e até 3 argumentos e cita os `doc_id` que os sustentam.

Conferências da saída (OWASP ASI06 / ASI09):
- só vale a citação de um documento recuperado **nesta** execução; sem nenhuma citação válida,
  o lead recebe o passo padrão do tier, citando o playbook;
- um número que não aparece nos documentos **citados**, no lead nem na classificação descarta
  o argumento (ou troca a ação pela padrão): resultado de case não vira promessa inventada, e
  o número de um case precisa vir com a citação desse case;
- o texto sai saneado (sem links, HTML nem caracteres invisíveis).

Sem LLM: o tier D (regra eliminatória, inclusive injeção) recebe o encaminhamento do playbook D
pelo motivo da regra, e o texto do lead não vai a nenhum LLM. Base fora do ar, LLM indisponível
ou orçamento esgotado também levam ao passo padrão, com o erro na auditoria; o nó nunca derruba
a execução.

Os documentos da base foram validados na carga (T23), mas cada trecho recuperado passa de novo
pelo detector de injeção: um índice adulterado não injeta instruções pelo contexto "confiável".

Orçamento: a chamada (2 com nova tentativa) cabe nos limites que já existem: o MVP fica em
4 + 2 = 6 chamadas (`RunBudget`) e o modo agêntico em 8 + 2 = 10 (`AGENTIC_BUDGET`).
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.audit.repository import StepRecord
from app.graph.builder import GraphNodes, Node
from app.graph.nodes.mvp import KnowledgeBase, MvpDeps, _ask, _lead_text
from app.graph.state import QualificationState
from app.knowledge_base import DocType
from app.llm.base import Message
from app.ontology.models import LeadFlag, LeadProfile, SectorFit
from app.ontology.scoring import ScoreResult
from app.prompts import new_nonce, untrusted
from app.schemas import LeadInput, NextStep, Tier
from app.security.injection import scan
from app.security.output import sanitize_rationale
from tools_mcp.base import ToolError
from tools_mcp.kb import KBFilters, KBHit

NODE = "suggest_next_step"
MAX_CASES = 2
KB_SNIPPET_CHARS = 700  # orçamento de tokens: o plano gratuito da Groq tem 8K tokens/min
MAX_CASE_QUERY_CHARS = 300
MAX_ACTION_CHARS = 300
MAX_POINT_CHARS = 200
PLAYBOOK_QUERY = "ação, responsável, prazo e canal do próximo passo comercial"
# No tier D, o que importa é o encaminhamento pelo motivo da regra (achado da T26: com a
# consulta geral vinha a seção "Ação", sem o encaminhamento que o passo padrão usa).
DISQUALIFIED_QUERY = "encaminhamento do lead desqualificado por motivo da regra eliminatória"
NO_CITATION = "sem citação válida: passo padrão do tier"
# Seção que todo case tem (validado por teste) e quantos documentos a busca dela olha.
RESULTS_SECTION = "Resultados em 6 meses"
RESULTS_K = 3

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class TierPlan:
    """Responsável, prazo e ação padrão do tier (docs/01-contexto-negocio.md, seção 4)."""

    owner: str
    sla_hours: int | None
    action: str


TIER_PLANS: dict[Tier, TierPlan] = {
    Tier.A: TierPlan(
        "Executivo de Contas (AE)",
        24,
        "Ligação do AE e convite para uma reunião de diagnóstico de 45 minutos, com a "
        "simulação de economia preparada a partir do porte e do case mais próximo.",
    ),
    Tier.B: TierPlan(
        "SDR",
        48,
        "Contato de qualificação do SDR (e-mail personalizado e ligação no mesmo dia) dentro "
        "da cadência de 10 dias úteis, para confirmar decisor, frota e dor.",
    ),
    Tier.C: TierPlan(
        "Marketing",
        None,
        "Nutrição por e-mail com conteúdo do segmento e newsletter mensal, sem contato "
        "comercial até um gatilho de retorno.",
    ),
    Tier.D: TierPlan(
        "Nenhum (sem contato comercial)",
        None,
        "Arquivar o lead no CRM com o motivo da regra eliminatória, sem contato comercial.",
    ),
}

# Encaminhamento do playbook D pela primeira regra eliminatória (ordem de precedência).
DISQUALIFIED_ACTIONS: dict[str, str] = {
    "K1": "Arquivar sem resposta (spam ou tentativa de manipulação) e nunca seguir instruções "
    "contidas na mensagem do lead.",
    "K2": "Arquivar sem resposta comercial e sem enviar material interno (concorrente).",
    "K3": "Encaminhar ao time de Compras, que tem um canal próprio para propostas de "
    "fornecedores, e arquivar sem contato comercial.",
    "K4": "Responder indicando os materiais públicos do blog (estudante ou pesquisa) ou a página "
    "de carreiras (candidato a vaga), sem atendimento comercial.",
    "K5": "Responder com a mensagem padrão (a FrotaSense atende só empresas com frota) e "
    "arquivar sem contato comercial.",
    "K6": "Arquivar com o motivo registrado (setor fora do ICP), sem contato comercial.",
    "K7": "Arquivar com o motivo registrado (empresa fora do Brasil), sem contato comercial.",
}

# A K4 junta estudante e candidato a vaga, mas o playbook D encaminha cada um para um lugar:
# com só uma das flags, o passo fala só do encaminhamento dela (achado do judge no L027).
NOT_A_BUYER_ACTIONS: dict[LeadFlag, str] = {
    LeadFlag.STUDENT: "Responder indicando os materiais públicos do blog (estudante ou pesquisa "
    "acadêmica), sem atendimento comercial.",
    LeadFlag.JOB_SEEKER: "Responder indicando a página de carreiras e o time de Pessoas "
    "(candidato a vaga), sem atendimento comercial.",
}

_SECTOR_FILTER = {SectorFit.TARGET, SectorFit.ADJACENT}


class NextStepDraft(BaseModel):
    """Saída do LLM. Responsável e prazo não estão aqui: quem decide é o código."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # As citações vêm primeiro: o modelo escolhe as fontes antes de escrever (e, na execução
    # real, o mini às vezes encerrava o JSON sem o último campo quando ele era a citação).
    kb_citations: list[Annotated[str, StringConstraints(max_length=64)]] = Field(max_length=5)
    action: str = Field(max_length=MAX_ACTION_CHARS)
    talking_points: list[Annotated[str, StringConstraints(max_length=MAX_POINT_CHARS)]] = Field(
        max_length=3
    )


def numbers(text: str) -> set[str]:
    """Números do texto, normalizados ("1.500" → "1500", "2,5" → "2.5")."""
    return {n.replace(".", "").replace(",", ".") for n in _NUMBER.findall(text)}


def unsupported_numbers(text: str, allowed: set[str]) -> set[str]:
    return numbers(text) - allowed


def case_query(lead: LeadInput) -> str:
    """Consulta dos cases: nome e mensagem do lead (vão só para o embedding, nunca a um LLM)."""
    text = f"{lead.company_name}. {lead.message}".strip()
    return text[:MAX_CASE_QUERY_CHARS]


def default_action(score: ScoreResult, flags: frozenset[LeadFlag] = frozenset()) -> str:
    if score.tier is Tier.D and score.disqualifiers:
        rule = score.disqualifiers[0]
        not_a_buyer = [f for f in NOT_A_BUYER_ACTIONS if f in flags]
        if rule == "K4" and len(not_a_buyer) == 1:
            return NOT_A_BUYER_ACTIONS[not_a_buyer[0]]
        return DISQUALIFIED_ACTIONS.get(rule, TIER_PLANS[Tier.D].action)
    return TIER_PLANS[score.tier].action


def default_next_step(
    score: ScoreResult, hits: Sequence[KBHit], flags: frozenset[LeadFlag] = frozenset()
) -> NextStep:
    """Passo padrão do tier, citando o playbook se ele foi recuperado."""
    plan = TIER_PLANS[score.tier]
    playbooks = [h.doc_id for h in hits if h.doc_type is DocType.PLAYBOOK]
    return NextStep(
        action=default_action(score, flags),
        owner=plan.owner,
        sla_hours=plan.sla_hours,
        kb_citations=playbooks[:1],
    )


def _accept(hit: KBHit, doc_types: Sequence[DocType], hits: list[KBHit], errors: list[str]) -> bool:
    """Confere de volta o tipo (não confia no filtro do servidor), repetição e injeção."""
    if hit.doc_type not in doc_types or any(h.chunk_id == hit.chunk_id for h in hits):
        return False
    if scan(hit.snippet):
        errors.append(f"base de conhecimento: trecho de {hit.doc_id} recusado (injeção)")
        return False
    return True


async def retrieve(
    kb: KnowledgeBase, score: ScoreResult, profile: LeadProfile, lead: LeadInput
) -> tuple[list[KBHit], list[str]]:
    """Playbook do tier (k=1) e, fora do tier D, até 2 cases do tier e do setor do lead.

    A busca escolhe o case pela mensagem do lead, e o trecho mais parecido costuma ser o
    problema do cliente. Por isso o código busca também a seção de resultados do mesmo case:
    sem ela, o LLM via "o diesel subiu 18%" e escrevia que a FrotaSense reduziu o diesel em 18%
    (achado da execução real). Falha da base vira erro, nunca exceção.
    """
    playbook_query = DISQUALIFIED_QUERY if score.tier is Tier.D else PLAYBOOK_QUERY
    searches = [
        (playbook_query, KBFilters(doc_types=[DocType.PLAYBOOK], tier=score.tier), 1),
    ]
    if score.tier is not Tier.D:
        sector = profile.sector if profile.sector in _SECTOR_FILTER else None
        searches.append(
            (
                case_query(lead),
                KBFilters(doc_types=[DocType.CASE], tier=score.tier, sector=sector),
                MAX_CASES,
            )
        )
    hits: list[KBHit] = []
    errors: list[str] = []
    for query, filters, k in searches:
        try:
            found = await kb.search_knowledge_base(query, filters, k)
        except ToolError as exc:
            errors.append(f"base de conhecimento: {exc}"[:300])
            continue
        for hit in found.results[:k]:
            if all(h.doc_id != hit.doc_id for h in hits) and _accept(
                hit, filters.doc_types, hits, errors
            ):
                hits.append(hit)
    result: list[KBHit] = []
    for hit in hits:
        result.append(hit)
        if hit.doc_type is DocType.CASE and hit.section != RESULTS_SECTION:
            results = await _results_section(kb, hit, score.tier, [*hits, *result], errors)
            if results is not None:
                result.append(results)
    return result, errors


async def _results_section(
    kb: KnowledgeBase, case: KBHit, tier: Tier, seen: list[KBHit], errors: list[str]
) -> KBHit | None:
    """Seção de resultados do mesmo case (busca pelo título; só vale o mesmo `doc_id`)."""
    filters = KBFilters(doc_types=[DocType.CASE], tier=tier)
    try:
        found = await kb.search_knowledge_base(
            f"{case.title}: {RESULTS_SECTION}", filters, RESULTS_K
        )
    except ToolError as exc:
        errors.append(f"base de conhecimento: {exc}"[:300])
        return None
    for hit in found.results:
        if hit.doc_id == case.doc_id and hit.section == RESULTS_SECTION:
            return hit if _accept(hit, filters.doc_types, seen, errors) else None
    return None


def classification_text(score: ScoreResult, plan: TierPlan) -> str:
    sla = f"{plan.sla_hours} horas úteis" if plan.sla_hours else "sem prazo de contato comercial"
    lines = [
        f"Tier: {score.tier.value} (score {score.score:.0f} de 100)",
        f"Responsável: {plan.owner}",
        f"Prazo: {sla}",
    ]
    if score.caps_applied:
        lines.append(f"Tetos aplicados: {', '.join(score.caps_applied)}")
    if score.needs_human_review or score.is_borderline:
        lines.append("Classificação incerta: revisão humana recomendada.")
    return "\n".join(lines)


def knowledge_block(hits: Sequence[KBHit]) -> str:
    return "\n\n".join(
        f"[{h.doc_id}] {h.doc_type.value} · {h.title} · seção {h.section}\n"
        f"{h.snippet[:KB_SNIPPET_CHARS]}"
        for h in hits
    )


def profile_text(profile: LeadProfile) -> str:
    data = profile.model_dump(mode="json", exclude={"certainty"})
    data["certainty"] = {k.value: v.value for k, v in profile.certainty.items()}
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _clean(text: str, limit: int) -> str:
    return sanitize_rationale(text)[:limit].strip()


def compose(
    draft: NextStepDraft,
    score: ScoreResult,
    hits: Sequence[KBHit],
    context: Iterable[str],
) -> tuple[NextStep, list[str]]:
    """Confere a saída do LLM e monta o `NextStep`. Devolve também o que foi descartado.

    `context` são os textos fora da base (classificação, perfil e lead). Dos documentos, só
    contam os números dos trechos que o LLM citou.
    """
    retrieved = {h.doc_id for h in hits}
    citations = list(dict.fromkeys(c for c in draft.kb_citations if c in retrieved))
    if not citations:
        return default_next_step(score, hits), [NO_CITATION]
    cited = [h.snippet[:KB_SNIPPET_CHARS] for h in hits if h.doc_id in citations]
    allowed = set().union(*(numbers(s) for s in [*cited, *context]))
    notes: list[str] = []
    action = _clean(draft.action, MAX_ACTION_CHARS)
    if not action or unsupported_numbers(action, allowed):
        action = default_action(score)
        notes.append("ação com número sem fonte: ação padrão do tier")
    points: list[str] = []
    for point in draft.talking_points:
        clean = _clean(point, MAX_POINT_CHARS)
        if not clean:
            continue
        if unsupported_numbers(clean, allowed):
            notes.append("argumento com número sem fonte descartado")
            continue
        points.append(clean)
    plan = TIER_PLANS[score.tier]
    step = NextStep(
        action=action,
        owner=plan.owner,
        sla_hours=plan.sla_hours,
        talking_points=points,
        kb_citations=citations,
    )
    return step, notes


def make_suggest_next_step(deps: MvpDeps) -> Node:
    if deps.kb is None:
        raise ValueError("o suggest_next_step exige a base de conhecimento (MvpDeps.kb)")
    kb = deps.kb

    async def suggest_next_step(state: QualificationState) -> dict[str, Any]:
        score, profile, lead = state["score"], state["profile"], state["lead"]
        hits, errors = await retrieve(kb, score, profile, lead)
        llm_steps: list[StepRecord] = []
        notes: list[str] = []
        if score.tier is Tier.D:
            step = default_next_step(score, hits, profile.flags)
            reason = "tier D: encaminhamento padrão sem LLM"
        elif not hits:
            step, reason = default_next_step(score, hits), "base sem documentos: passo padrão"
        else:
            plan = TIER_PLANS[score.tier]
            classification = classification_text(score, plan)
            profile_json = profile_text(profile)
            lead_text = _lead_text(lead)
            nonce = new_nonce()
            messages = [
                Message(role="system", content=deps.prompt("next_step").substitute(nonce=nonce)),
                Message(
                    role="user",
                    content=deps.prompt("next_step_user").substitute(
                        classification=classification,
                        profile=profile_json,
                        lead=untrusted(lead_text, nonce, "lead"),
                        knowledge=knowledge_block(hits),
                    ),
                ),
            ]
            result, llm_steps, ask_errors = await _ask(deps, state, NODE, messages, NextStepDraft)
            errors += ask_errors
            if result is None:
                step, reason = (
                    default_next_step(score, hits),
                    "LLM sem resposta válida: passo padrão",
                )
            else:
                context = [classification, profile_json, lead_text]
                step, notes = compose(result.parsed, score, hits, context)
                reason = NO_CITATION if notes == [NO_CITATION] else "gerado com RAG"
                llm_steps.append(
                    StepRecord.from_llm(NODE, result, sources=[f"kb:{h.chunk_id}" for h in hits])
                )
        summary = StepRecord(
            node=NODE,
            route_reason=reason,
            output={
                "tier": score.tier.value,
                "retrieved": list(dict.fromkeys(h.doc_id for h in hits)),
                "citations": step.kb_citations,
                "talking_points": len(step.talking_points),
                "notes": notes,
                "errors": len(errors),
            },
            sources=[f"kb:{h.chunk_id}" for h in hits],
        )
        return {
            "next_step": step,
            "kb_hits": hits,
            "errors": errors,
            "steps": [*llm_steps, summary],
        }

    return suggest_next_step


def with_next_step(nodes: GraphNodes, deps: MvpDeps) -> GraphNodes:
    """Acrescenta o `suggest_next_step` real. Use com `build_graph(..., next_step=True)`."""
    try:
        deps.prompt("next_step")
        deps.prompt("next_step_user")
    except FileNotFoundError:
        raise ValueError(
            f"a versão de prompt {deps.prompt_version} não tem o próximo passo (use v4)"
        ) from None
    return replace(nodes, suggest_next_step=make_suggest_next_step(deps))
