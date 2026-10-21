"""Nós em modo stub (T13): respostas fixas e determinísticas, sem rede nem LLM.

Servem para validar o formato do grafo e do state. A T14 troca cada um pela versão real,
sem mudar o builder.
"""

from datetime import UTC, datetime
from typing import Any

from app.audit.repository import StepRecord
from app.graph.nodes.core import build_result
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


def audit_log(state: QualificationState) -> dict[str, Any]:
    """Fecha a execução. A versão real (T14) também grava em `agent_runs`/`agent_steps`."""
    if state.get("status") == "rejected":
        return {"steps": [StepRecord(node="audit_log", output={"status": "rejected"})]}
    result = build_result(state)
    status = "needs_review" if result.needs_human_review else "completed"
    return {
        "result": result,
        "status": status,
        "steps": [StepRecord(node="audit_log", output={"status": status})],
    }
