"""State do grafo de qualificação (ver docs/00-arquitetura.md, seção 2).

Cada nó devolve só as chaves que alterou. As listas acumulam entre nós (reducer de soma): um
nó acrescenta evidências, passos de auditoria ou erros sem apagar os dos nós anteriores.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

from app.audit.repository import StepRecord
from app.ontology.models import LeadProfile
from app.ontology.scoring import ScoreResult
from app.schemas import Evidence, LeadInput, QualificationResult

PROMPT_VERSION = "v1"

Status = Literal["running", "rejected", "completed", "failed", "needs_review"]


class GraphInput(TypedDict):
    """Entrada do grafo: o payload ainda **não validado** e o id da execução."""

    run_id: str
    raw_input: dict[str, Any]


class QualificationState(GraphInput, total=False):
    prompt_version: str
    status: Status
    started_at: float  # epoch (s), para a latência total gravada na auditoria
    lead: LeadInput
    evidence: Annotated[list[Evidence], operator.add]
    research_iterations: int
    # Pesquisa agêntica (T25): consultas já feitas e a próxima, decidida pelo código.
    research_queries: list[str]
    research_next: str | None
    profile: LeadProfile
    # Ids (E1, E2...) das evidências que o LLM citou na extração, já filtrados.
    evidence_ids: list[str]
    # Padrões de injeção achados pelas regras determinísticas ("origem:família").
    injection_hits: list[str]
    # Justificativa em linguagem natural do assess (o LLM justifica; o código pontua).
    rationale: str
    confidence: float
    score: ScoreResult
    result: QualificationResult
    # Ids gravados no HubSpot pelo `write_to_crm` (company_id, contact_id, note_id).
    crm: dict[str, str]
    steps: Annotated[list[StepRecord], operator.add]
    errors: Annotated[list[str], operator.add]


# Chaves que o state final sempre tem, em qualquer caminho (feliz ou rejeitado).
FINAL_KEYS = frozenset(
    {"run_id", "raw_input", "prompt_version", "status", "started_at", "steps", "errors"}
)
# Chaves adicionais do caminho feliz.
HAPPY_PATH_KEYS = FINAL_KEYS | {
    "lead",
    "evidence",
    "research_iterations",
    "profile",
    "rationale",
    "confidence",
    "score",
    "result",
}
