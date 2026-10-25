"""Nós determinísticos (sem LLM): validação da entrada, score e montagem do resultado."""

import time
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.audit.repository import FinalStatus, StepRecord
from app.graph.state import PROMPT_VERSION, QualificationState
from app.ontology.models import LeadProfile
from app.ontology.scoring import compute_score as score_profile
from app.schemas import LeadInput, QualificationResult

MAX_VALIDATION_ERRORS = 5
# Teto fixo de iterações da pesquisa agêntica (T25), conferido pelo roteador independente dos
# limites configurados no nó: nem um nó com defeito gera loop infinito.
HARD_MAX_ITERATIONS = 3


def validate_input(state: QualificationState) -> dict[str, Any]:
    """Valida o payload contra o `LeadInput` (sanitização, SSRF no domínio, campos extras)."""
    try:
        lead = LeadInput.model_validate(state["raw_input"])
    except ValidationError as exc:
        # Só o local e o tipo do erro: a mensagem do pydantic pode ecoar o texto do lead.
        details = [
            f"{'.'.join(str(p) for p in err['loc']) or 'entrada'}: {err['type']}"
            for err in exc.errors(include_input=False, include_url=False)[:MAX_VALIDATION_ERRORS]
        ]
        return {
            "prompt_version": PROMPT_VERSION,
            "started_at": time.time(),
            "status": "rejected",
            "errors": [f"entrada inválida: {d}" for d in details],
            "steps": [StepRecord(node="validate_input", output={"valid": False})],
        }
    return {
        "prompt_version": PROMPT_VERSION,
        "started_at": time.time(),
        "status": "running",
        "lead": lead,
        "steps": [StepRecord(node="validate_input", output={"valid": True})],
    }


def route_after_validation(state: QualificationState) -> str:
    return "reject" if state.get("status") == "rejected" else "continue"


def route_unless_failed(state: QualificationState) -> str:
    return "fail" if state.get("status") == "failed" else "continue"


def route_research(state: QualificationState) -> str:
    """Volta ao `agentic_research` só se há consulta pendente e o teto fixo não foi atingido."""
    pending = state.get("research_next")
    if pending and state.get("research_iterations", 0) < HARD_MAX_ITERATIONS:
        return "continue"
    return "done"


def compute_score(state: QualificationState) -> dict[str, Any]:
    """Rubrica determinística (T07). O LLM nunca decide a pontuação."""
    profile = state.get("profile") or LeadProfile()
    result = score_profile(profile)
    return {
        "score": result,
        "steps": [
            StepRecord(
                node="compute_score",
                output={
                    "score": result.score,
                    "tier": result.tier.value,
                    "disqualifiers": list(result.disqualifiers),
                    "caps": list(result.caps_applied),
                },
            )
        ],
    }


def build_result(state: QualificationState) -> QualificationResult:
    """Monta o `QualificationResult` a partir do state (usado pelo `audit_log`)."""
    score = state["score"]
    cost = sum((s.cost_usd for s in state.get("steps", [])), start=Decimal(0))
    return QualificationResult(
        run_id=state["run_id"],
        tier=score.tier,
        score=score.score,
        is_borderline=score.is_borderline,
        confidence=state.get("confidence", 0.0),
        needs_human_review=score.needs_human_review,
        disqualifiers=list(score.disqualifiers),
        caps_applied=list(score.caps_applied),
        criteria=list(score.breakdown),
        rationale=state.get("rationale", ""),
        prompt_version=state.get("prompt_version", PROMPT_VERSION),
        cost_usd=float(cost),
    )


def finalize(state: QualificationState) -> tuple[FinalStatus, QualificationResult | None]:
    """Status final e resultado. Rejeitado ou falho não tem resultado (nem tier)."""
    status = state.get("status", "failed")
    if status not in {"rejected", "failed"} and "result" in state:
        return "completed", state["result"]  # o baseline já devolve o resultado pronto
    if status in {"rejected", "failed"} or "score" not in state:
        return ("rejected" if status == "rejected" else "failed"), None
    result = build_result(state)
    return ("needs_review" if result.needs_human_review else "completed"), result


def latency_ms(state: QualificationState) -> int:
    started = state.get("started_at")
    return max(0, round((time.time() - started) * 1000)) if started else 0
