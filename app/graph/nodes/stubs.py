"""Nós em modo stub (T13): respostas fixas e determinísticas, sem rede nem LLM.

Servem para validar o formato do grafo e do state. A T14 troca cada um pela versão real,
sem mudar o builder.
"""

from datetime import UTC, datetime
from typing import Any

from app.audit.repository import StepRecord
from app.graph.nodes.core import finalize
from app.graph.state import QualificationState
from app.ontology.models import LeadProfile
from app.schemas import Evidence, EvidenceSource

STUB_RATIONALE = "stub: sem avaliação de LLM (T13)"


def research(state: QualificationState) -> dict[str, Any]:
    lead = state["lead"]
    evidence = Evidence(
        source_type=EvidenceSource.LEAD_MESSAGE,
        snippet=(lead.message or lead.company_name)[:1000],
        retrieved_at=datetime.now(UTC),
    )
    return {
        "evidence": [evidence],
        "research_iterations": state.get("research_iterations", 0) + 1,
        "steps": [StepRecord(node="research", output={"evidence": 1})],
    }


def normalize(state: QualificationState) -> dict[str, Any]:
    profile = LeadProfile()  # tudo `unknown`: o stub não extrai nada
    return {
        "profile": profile,
        "steps": [StepRecord(node="normalize", output=profile.model_dump(mode="json"))],
    }


def assess(state: QualificationState) -> dict[str, Any]:
    return {
        "rationale": STUB_RATIONALE,
        "confidence": 0.0,
        "steps": [StepRecord(node="assess", output={"confidence": 0.0})],
    }


def write_to_crm(state: QualificationState) -> dict[str, Any]:
    """CRM desligado (avaliações e testes): nada é gravado no HubSpot."""
    return {"steps": [StepRecord(node="write_to_crm", route_reason="CRM desativado")]}


def audit_log(state: QualificationState) -> dict[str, Any]:
    """Fecha a execução sem gravar no banco (a versão real está em `nodes/mvp.py`)."""
    status, result = finalize(state)
    update: dict[str, Any] = {
        "status": status,
        "steps": [StepRecord(node="audit_log", output={"status": status})],
    }
    if result is not None:
        update["result"] = result
    return update
