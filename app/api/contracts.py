"""Contratos de saída da API, compartilhados pela REST (`main.py`) e pelo MCP (`mcp_server.py`)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.audit.repository import RunView

RunStatus = Literal["running", "completed", "failed", "needs_review", "rejected"]
# Fora da saída: a entrada (dados pessoais), os passos internos (ficam na auditoria do banco) e
# a decisão humana crua (a aplicada está em `result.review`).
HIDDEN_FIELDS = {"lead_input", "steps", "next_step", "review"}


class QualifyAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: uuid.UUID
    status: Literal["running"] = "running"
    status_url: str


class RunOut(BaseModel):
    """Execução sem os passos internos (esses ficam na auditoria do banco)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: uuid.UUID
    status: RunStatus
    created_at: datetime
    finished_at: datetime | None
    prompt_version: str
    tier: str | None
    score: Decimal | None
    confidence: Decimal | None
    result: dict[str, Any] | None
    cost_usd: Decimal
    latency_ms: int | None
    crm_ids: dict[str, Any] | None
    errors: list[str]
    # Revisão humana (T31): quando a execução parou esperando a decisão (a decisão aplicada
    # fica em `result.review`).
    review_requested_at: datetime | None = None


def run_out(run: RunView) -> RunOut:
    return RunOut.model_validate(run.model_dump(exclude=HIDDEN_FIELDS))
