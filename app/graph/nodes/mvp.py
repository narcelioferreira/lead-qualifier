"""Nós reais do MVP (T14): pesquisa simples, extração e justificativa com o mini, auditoria.

As dependências (LLM, busca, site, auditoria) são injetadas por `MvpDeps`: produção usa Groq,
Tavily, sites e Postgres; os testes de grafo usam mocks com respostas fixas.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from app.audit.repository import AuditRepository, StepRecord
from app.graph.builder import GraphNodes
from app.graph.nodes.core import finalize, latency_ms
from app.graph.nodes.extraction import (
    Assessment,
    Extraction,
    cnae_in_evidence,
    confidence,
    to_profile,
)
from app.graph.state import QualificationState
from app.llm.base import LLMError, LLMOutputError, LLMResult, Message, StructuredLLM
from app.prompts import load_prompt, new_nonce, untrusted
from app.routing.cost import ModelSpec, get_catalog
from app.schemas import Evidence, EvidenceSource, LeadInput
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
class MvpDeps:
    llm: StructuredLLM
    search: Searcher
    site: SiteReader
    audit: AuditRepository | None = None
    model_key: str = "groq-mini"

    @property
    def spec(self) -> ModelSpec:
        return get_catalog().get(self.model_key)


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
    deps: MvpDeps, node: str, messages: list[Message], schema: type[T]
) -> tuple[LLMResult[T] | None, list[StepRecord], list[str]]:
    """Chama o LLM com 1 nova tentativa para saída fora do schema. Nunca levanta."""
    steps: list[StepRecord] = []
    for attempt in (1, 2):
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
        nonce = new_nonce()
        messages = [
            Message(role="system", content=load_prompt("normalize").substitute(nonce=nonce)),
            Message(
                role="user",
                content=load_prompt("normalize_user").substitute(
                    lead=untrusted(_lead_text(state["lead"]), nonce, "lead"),
                    evidence=_evidence_block(evidence, ids, nonce),
                ),
            ),
        ]
        result, steps, errors = await _ask(deps, "normalize", messages, Extraction)
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
            "profile": profile,
            "evidence_ids": cited,
            "confidence": confidence(profile),
            "steps": [
                *steps,
                StepRecord.from_llm("normalize", result, sources=sources),
            ],
        }

    async def assess(state: QualificationState) -> dict[str, Any]:
        evidence = state.get("evidence", [])
        cited = state.get("evidence_ids") or evidence_ids(evidence)
        nonce = new_nonce()
        profile = state["profile"].model_dump(mode="json", exclude={"certainty"})
        profile["certainty"] = {k.value: v.value for k, v in state["profile"].certainty.items()}
        messages = [
            Message(role="system", content=load_prompt("assess").substitute(nonce=nonce)),
            Message(
                role="user",
                content=load_prompt("assess_user").substitute(
                    profile=json.dumps(profile, ensure_ascii=False, sort_keys=True),
                    evidence=_evidence_block(evidence, cited, nonce),
                ),
            ),
        ]
        result, steps, errors = await _ask(deps, "assess", messages, Assessment)
        if result is None:
            # A justificativa é acessória: o score ainda pode ser calculado.
            return {
                "rationale": "Justificativa indisponível (falha do LLM); ver auditoria.",
                "errors": errors,
                "steps": steps,
            }
        return {
            "rationale": result.parsed.rationale,
            "steps": [*steps, StepRecord.from_llm("assess", result)],
        }

    async def audit_log(state: QualificationState) -> dict[str, Any]:
        status, result = finalize(state)
        step = StepRecord(node="audit_log", output={"status": status})
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
                )
            except Exception as exc:
                update["errors"] = [f"audit_log: falha ao gravar ({type(exc).__name__})"]
        return update

    return GraphNodes(research=research, normalize=normalize, assess=assess, audit_log=audit_log)
