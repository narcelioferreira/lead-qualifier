"""Nós reais do MVP (T14): pesquisa simples, extração e justificativa com o mini, auditoria.

As dependências (LLM, busca, site, CRM, auditoria) são injetadas por `MvpDeps`: produção usa
Groq, o servidor MCP `lead-tools` (busca, site e HubSpot, desde a T20) e Postgres; os testes de
grafo usam mocks com respostas fixas.
"""

import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from string import Template
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.audit.repository import AuditRepository, StepRecord
from app.graph.builder import GraphNodes, Node
from app.graph.nodes import stubs
from app.graph.nodes.core import finalize, latency_ms
from app.graph.nodes.crm import CrmWriter, make_write_to_crm
from app.graph.nodes.extraction import (
    Assessment,
    Extraction,
    cnae_in_evidence,
    confidence,
    to_profile,
)
from app.graph.state import QualificationState
from app.llm.base import LLMError, LLMOutputError, LLMResult, Message, StructuredLLM
from app.ontology.models import LeadFlag, LeadProfile
from app.prompts import load_prompt, new_nonce, untrusted
from app.routing.cost import ModelSpec, get_catalog
from app.schemas import Evidence, EvidenceSource, LeadInput, QualificationResult, Tier
from app.security.injection import InjectionHit, scan_sources
from app.security.output import sanitize_rationale
from tools_mcp.base import ToolError
from tools_mcp.search import SearchResult
from tools_mcp.site import SiteContent

MAX_SEARCH_RESULTS = 3
SEARCH_SNIPPET_CHARS = 500  # orçamento de tokens: o plano gratuito da Groq tem 8K tokens/min
SITE_SNIPPET_CHARS = 1000
RETRY_NOTICE = (
    "Sua resposta anterior não seguiu o formato pedido. Responda somente com o JSON no schema."
)


class Searcher(Protocol):
    async def search(self, query: str) -> SearchResult: ...


class SiteReader(Protocol):
    async def fetch(self, domain: str) -> SiteContent: ...


@dataclass(frozen=True)
class RunBudget:
    """Limites por execução (OWASP ASI08 / AST08): contém loops, retries e exaustão de recursos.

    O MVP usa 2 chamadas (4 com retries) e ~3,4K tokens por lead; os limites dão folga para
    variação normal, mas cortam um lead que force saídas inválidas ou contexto gigante.
    """

    max_llm_calls: int = 6
    max_tokens: int = 24_000
    max_seconds: float = 300.0

    def exceeded(self, steps: Sequence[StepRecord], started_at: float | None) -> str | None:
        """Motivo do estouro, ou `None` se ainda há orçamento para mais uma chamada."""
        calls = sum(
            1 for s in steps if s.model_key or (s.route_reason or "").startswith("tentativa")
        )
        tokens = sum(s.usage.input_tokens + s.usage.output_tokens for s in steps)
        elapsed = time.time() - started_at if started_at else 0.0
        if calls >= self.max_llm_calls:
            return f"{calls} chamadas ao LLM, limite {self.max_llm_calls}"
        if tokens >= self.max_tokens:
            return f"{tokens} tokens, limite {self.max_tokens}"
        if elapsed >= self.max_seconds:
            return f"{elapsed:.0f} s, limite {self.max_seconds:.0f} s"
        return None


@dataclass(frozen=True)
class MvpDeps:
    llm: StructuredLLM
    search: Searcher
    site: SiteReader
    audit: AuditRepository | None = None
    # `None` desliga o CRM (avaliações): o nó `write_to_crm` só registra que não gravou.
    crm: CrmWriter | None = None
    model_key: str = "groq-mini"
    prompt_version: str = "v1"
    # Digest da configuração verificada (app/integrity.py), gravado em cada execução.
    config_digest: str | None = None
    budget: RunBudget = field(default_factory=RunBudget)

    @property
    def spec(self) -> ModelSpec:
        return get_catalog().get(self.model_key)

    def prompt(self, name: str) -> Template:
        return load_prompt(name, self.prompt_version)


def evidence_ids(evidence: Sequence[Evidence]) -> list[str]:
    return [f"E{i}" for i in range(1, len(evidence) + 1)]


def _lead_text(lead: LeadInput) -> str:
    # O e-mail não vai para o LLM: não ajuda a classificar e é dado pessoal.
    return "\n".join(
        [
            f"Empresa: {lead.company_name}",
            f"Domínio: {lead.company_domain or '(não informado)'}",
            f"Cargo do contato: {lead.contact_role}",
            f"Origem: {lead.source.value}",
            f"Mensagem: {lead.message or '(vazia)'}",
        ]
    )


def injection_hits(
    lead: LeadInput, evidence: Sequence[Evidence], ids: Sequence[str]
) -> list[InjectionHit]:
    """Varre o que o lead controla: mensagem, cargo, nome e o site da própria empresa.

    Resultados de busca (páginas de terceiros) ficam de fora: um artigo sobre prompt injection
    no LinkedIn não pode desqualificar a transportadora.
    """
    sources = [("lead", f"{lead.company_name}\n{lead.contact_role}\n{lead.message}")]
    sources += [
        (eid, ev.snippet)
        for eid, ev in zip(ids, evidence, strict=True)
        if ev.source_type is EvidenceSource.COMPANY_SITE
    ]
    return scan_sources(sources)


def _evidence_urls(evidence: Sequence[Evidence]) -> list[str]:
    return [str(e.source_url) for e in evidence if e.source_url is not None]


def _evidence_block(evidence: Sequence[Evidence], ids: Sequence[str], nonce: str) -> str:
    if not evidence:
        return "(nenhuma evidência)"
    blocks = []
    for eid, ev in zip(evidence_ids(evidence), evidence, strict=True):
        if eid not in ids:
            continue
        header = f"[{eid}] {ev.source_type.value}" + (f" {ev.source_url}" if ev.source_url else "")
        blocks.append(f"{header}\n{untrusted(ev.snippet, nonce, eid)}")
    return "\n\n".join(blocks)


async def _ask[T: BaseModel](
    deps: MvpDeps,
    state: QualificationState,
    node: str,
    messages: list[Message],
    schema: type[T],
) -> tuple[LLMResult[T] | None, list[StepRecord], list[str]]:
    """Chama o LLM com 1 nova tentativa para saída fora do schema. Nunca levanta.

    Antes de cada chamada confere o orçamento da execução (ASI08): estourou, não chama.
    """
    steps: list[StepRecord] = []
    for attempt in (1, 2):
        exceeded = deps.budget.exceeded([*state.get("steps", []), *steps], state.get("started_at"))
        if exceeded:
            return None, steps, [f"{node}: orçamento da execução excedido ({exceeded})"]
        try:
            result = await deps.llm.structured(deps.spec, messages, schema)
        except LLMOutputError as exc:
            steps.append(StepRecord(node=node, route_reason=f"tentativa {attempt}: {exc}"[:300]))
            messages = [*messages, Message(role="user", content=RETRY_NOTICE)]
            continue
        except LLMError as exc:
            return None, steps, [f"{node}: {exc}"]
        return result, steps, []
    return None, steps, [f"{node}: saída do LLM inválida após 2 tentativas"]


def make_nodes(deps: MvpDeps) -> GraphNodes:
    async def research(state: QualificationState) -> dict[str, Any]:
        lead = state["lead"]
        now = datetime.now(UTC)
        evidence = [
            Evidence(
                source_type=EvidenceSource.LEAD_MESSAGE,
                snippet=f"Cargo: {lead.contact_role}. Mensagem: {lead.message or '(vazia)'}"[:1000],
                retrieved_at=now,
            )
        ]
        errors: list[str] = []
        if lead.company_domain:
            try:
                site = await deps.site.fetch(lead.company_domain)
            except ToolError as exc:
                errors.append(f"site: {exc}")
            else:
                errors += [f"site: {e}" for e in site.errors]
                evidence += [
                    Evidence(
                        source_type=EvidenceSource.COMPANY_SITE,
                        source_url=page.url,
                        snippet=page.text[:SITE_SNIPPET_CHARS] or "(página sem texto)",
                        retrieved_at=site.retrieved_at,
                    )
                    for page in site.pages
                ]
        try:
            found = await deps.search.search(f"{lead.company_name} empresa")
        except ToolError as exc:
            errors.append(f"busca: {exc}")
        else:
            evidence += [
                Evidence(
                    source_type=EvidenceSource.WEB_SEARCH,
                    source_url=r.url,
                    snippet=f"{r.title}: {r.snippet}"[:SEARCH_SNIPPET_CHARS],
                    retrieved_at=found.retrieved_at,
                )
                for r in found.results[:MAX_SEARCH_RESULTS]
            ]
        return {
            "evidence": evidence,
            "research_iterations": state.get("research_iterations", 0) + 1,
            "errors": errors,
            "steps": [
                StepRecord(
                    node="research",
                    output={"evidence": len(evidence), "errors": len(errors)},
                    sources=[str(e.source_url) for e in evidence if e.source_url],
                )
            ],
        }

    async def normalize(state: QualificationState) -> dict[str, Any]:
        evidence = state.get("evidence", [])
        ids = evidence_ids(evidence)
        hits = injection_hits(state["lead"], evidence, ids)
        if hits:
            # Injeção conhecida: o texto não vai ao LLM e o lead cai na K1 (OWASP ASI01).
            profile = LeadProfile(flags=frozenset({LeadFlag.INJECTION}))
            return {
                "prompt_version": deps.prompt_version,
                "profile": profile,
                "evidence_ids": sorted({h.source for h in hits if h.source in ids}),
                "confidence": confidence(profile),
                "injection_hits": [f"{h.source}:{h.family}" for h in hits],
                "steps": [
                    StepRecord(
                        node="normalize",
                        route_reason="injeção detectada por regra: LLM não chamado",
                        output={"injection_hits": [f"{h.source}:{h.family}" for h in hits]},
                    )
                ],
            }
        nonce = new_nonce()
        messages = [
            Message(role="system", content=deps.prompt("normalize").substitute(nonce=nonce)),
            Message(
                role="user",
                content=deps.prompt("normalize_user").substitute(
                    lead=untrusted(_lead_text(state["lead"]), nonce, "lead"),
                    evidence=_evidence_block(evidence, ids, nonce),
                ),
            ),
        ]
        result, steps, errors = await _ask(deps, state, "normalize", messages, Extraction)
        if result is None:
            return {"status": "failed", "errors": errors, "steps": steps}
        extraction = result.parsed
        cited = [i for i in extraction.evidence_ids if i in ids]  # descarta ids inventados
        texts = [_lead_text(state["lead"]), *(e.snippet for e in evidence)]
        if extraction.cnae and not cnae_in_evidence(extraction.cnae, texts):
            # CNAE que não está em nenhuma evidência é alucinação: não pode decidir o setor.
            extraction = extraction.model_copy(update={"cnae": None})
        profile = to_profile(extraction)
        urls = [evidence[ids.index(i)].source_url for i in cited]
        sources = [str(u) for u in urls if u is not None]
        return {
            "prompt_version": deps.prompt_version,
            "profile": profile,
            "evidence_ids": cited,
            "confidence": confidence(profile),
            "steps": [
                *steps,
                StepRecord.from_llm("normalize", result, sources=sources),
            ],
        }

    async def assess(state: QualificationState) -> dict[str, Any]:
        if state.get("injection_hits"):
            families = sorted({h.split(":", 1)[1] for h in state["injection_hits"]})
            return {
                "rationale": (
                    "Lead desqualificado: tentativa de manipulação do avaliador detectada por "
                    f"regra determinística ({', '.join(families)}). "
                    "O conteúdo não foi enviado ao LLM."
                ),
                "steps": [StepRecord(node="assess", route_reason="injeção detectada: sem LLM")],
            }
        evidence = state.get("evidence", [])
        cited = state.get("evidence_ids") or evidence_ids(evidence)
        nonce = new_nonce()
        profile = state["profile"].model_dump(mode="json", exclude={"certainty"})
        profile["certainty"] = {k.value: v.value for k, v in state["profile"].certainty.items()}
        messages = [
            Message(role="system", content=deps.prompt("assess").substitute(nonce=nonce)),
            Message(
                role="user",
                content=deps.prompt("assess_user").substitute(
                    profile=json.dumps(profile, ensure_ascii=False, sort_keys=True),
                    evidence=_evidence_block(evidence, cited, nonce),
                ),
            ),
        ]
        result, steps, errors = await _ask(deps, state, "assess", messages, Assessment)
        if result is None:
            # A justificativa é acessória: o score ainda pode ser calculado.
            return {
                "rationale": "Justificativa indisponível (falha do LLM); ver auditoria.",
                "errors": errors,
                "steps": steps,
            }
        return {
            "rationale": sanitize_rationale(result.parsed.rationale, _evidence_urls(evidence)),
            "steps": [*steps, StepRecord.from_llm("assess", result)],
        }

    async def audit_log(state: QualificationState) -> dict[str, Any]:
        status, result = finalize(state)
        step = StepRecord(
            node="audit_log", output={"status": status, "config_digest": deps.config_digest}
        )
        update: dict[str, Any] = {"status": status, "steps": [step]}
        if result is not None:
            update["result"] = result
        if deps.audit is not None:
            try:
                await deps.audit.record_run(
                    run_id=uuid.UUID(state["run_id"]),
                    prompt_version=state.get("prompt_version", "v1"),
                    lead=state.get("lead"),
                    status=status,
                    steps=[*state.get("steps", []), step],
                    result=result,
                    errors=state.get("errors", []),
                    latency_ms=latency_ms(state),
                    rejected_fields=list(state.get("raw_input", {})) if "lead" not in state else (),
                    crm_ids=state.get("crm"),
                )
            except Exception as exc:
                update["errors"] = [f"audit_log: falha ao gravar ({type(exc).__name__})"]
        return update

    return GraphNodes(
        research=research,
        normalize=normalize,
        assess=assess,
        write_to_crm=make_write_to_crm(deps.crm) if deps.crm else stubs.write_to_crm,
        audit_log=audit_log,
    )


BASELINE_PROMPT_VERSION = "baseline-v1"


class BaselineAnswer(BaseModel):
    """Saída do baseline: o LLM decide tier e nota sozinho (é o que a T16 compara)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Tier
    score: int = Field(ge=0, le=100)
    rationale: str = Field(max_length=2000)


def make_baseline_nodes(deps: MvpDeps) -> tuple[Node, Node, Node]:
    """(research, classify, audit_log): pesquisa e auditoria iguais às do MVP."""
    mvp = make_nodes(deps)

    async def classify(state: QualificationState) -> dict[str, Any]:
        evidence = state.get("evidence", [])
        nonce = new_nonce()
        messages = [
            Message(role="system", content=deps.prompt("baseline").substitute(nonce=nonce)),
            Message(
                role="user",
                content=deps.prompt("baseline_user").substitute(
                    lead=untrusted(_lead_text(state["lead"]), nonce, "lead"),
                    evidence=_evidence_block(evidence, evidence_ids(evidence), nonce),
                ),
            ),
        ]
        result, steps, errors = await _ask(deps, state, "classify", messages, BaselineAnswer)
        if result is None:
            return {"status": "failed", "errors": errors, "steps": steps}
        answer = result.parsed
        qualification = QualificationResult(
            run_id=state["run_id"],
            tier=answer.tier,
            score=answer.score,
            is_borderline=False,
            confidence=0.0,  # o baseline não tem medida de incerteza
            needs_human_review=False,
            criteria=[],
            rationale=sanitize_rationale(answer.rationale, _evidence_urls(evidence)),
            prompt_version=BASELINE_PROMPT_VERSION,
            cost_usd=float(result.cost_usd),
        )
        return {
            "prompt_version": BASELINE_PROMPT_VERSION,
            "result": qualification,
            "steps": [*steps, StepRecord.from_llm("classify", result)],
        }

    return mvp.research, classify, mvp.audit_log
