"""Auditoria em memória com o mesmo contrato do `AuditRepository` (demo offline e testes).

Não persiste nada: serve para rodar a API e o grafo sem Postgres (demo no GitHub Actions, T22)
e para os testes da API. As regras de estado são as mesmas do banco: execução encerrada não
muda, e o e-mail do lead fica mascarado.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.audit.repository import (
    AuditError,
    RunSummary,
    RunView,
    StepRecord,
    StepView,
    audit_lead_input,
)
from app.schemas import LeadInput, QualificationResult


class MemoryAuditRepository:
    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, dict[str, Any]] = {}

    def _new(self, run_id: uuid.UUID, prompt_version: str, lead_input: dict[str, Any]) -> None:
        self.runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "created_at": datetime.now(UTC),
            "finished_at": None,
            "prompt_version": prompt_version,
            "lead_input": lead_input,
            "tier": None,
            "score": None,
            "confidence": None,
            "next_step": None,
            "result": None,
            "cost_usd": Decimal(0),
            "latency_ms": None,
            "crm_ids": None,
            "errors": [],
            "steps": [],
        }

    def _running(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = self.runs.get(run_id)
        if run is None:
            raise AuditError(f"execução {run_id} não existe")
        if run["status"] != "running":
            raise AuditError(f"execução {run_id} já foi encerrada ({run['status']})")
        return run

    def _close(self, run: dict[str, Any], latency_ms: int) -> None:
        run["cost_usd"] = sum((s.cost_usd for s in run["steps"]), Decimal(0))
        run["latency_ms"] = latency_ms
        run["finished_at"] = datetime.now(UTC)

    async def start_run(
        self, lead: LeadInput, prompt_version: str, run_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        run_id = run_id or uuid.uuid4()
        self._new(run_id, prompt_version, audit_lead_input(lead))
        return run_id

    async def fail_run(self, run_id: uuid.UUID, errors: Sequence[str], latency_ms: int) -> None:
        run = self._running(run_id)
        run |= {"status": "failed", "errors": list(errors)}
        self._close(run, latency_ms)

    async def fail_orphan_runs(self, message: str) -> int:
        orphans = [r for r in self.runs.values() if r["status"] == "running"]
        for run in orphans:
            run |= {"status": "failed", "errors": [message], "finished_at": datetime.now(UTC)}
        return len(orphans)

    async def record_run(
        self,
        *,
        run_id: uuid.UUID,
        prompt_version: str,
        lead: LeadInput | None,
        status: str,
        steps: Sequence[StepRecord],
        result: QualificationResult | None = None,
        errors: Sequence[str] = (),
        latency_ms: int,
        rejected_fields: Sequence[str] = (),
        crm_ids: dict[str, Any] | None = None,
    ) -> None:
        if result is not None and result.run_id != str(run_id):
            raise AuditError("run_id do resultado não confere com a execução")
        lead_input = (
            audit_lead_input(lead)
            if lead is not None
            else {"rejected": True, "fields": sorted(rejected_fields)}
        )
        if run_id not in self.runs:
            self._new(run_id, prompt_version, lead_input)
        run = self._running(run_id)
        now = datetime.now(UTC)
        run |= {
            "status": status,
            "prompt_version": prompt_version,
            "lead_input": lead_input,
            "errors": list(errors),
            "crm_ids": crm_ids or None,
            "steps": [
                StepView(id=i, created_at=now, **s.model_dump())
                for i, s in enumerate(steps, start=1)
            ],
        }
        if result is not None:
            run |= {
                "tier": result.tier.value,
                "score": Decimal(str(result.score)),
                "confidence": Decimal(str(result.confidence)),
                "next_step": result.next_step.model_dump(mode="json") if result.next_step else None,
                "result": result.model_dump(mode="json"),
            }
        self._close(run, latency_ms)

    async def get_run(self, run_id: uuid.UUID) -> RunView | None:
        run = self.runs.get(run_id)
        return None if run is None else RunView.model_validate(run)

    async def list_runs(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[RunSummary]:
        runs = sorted(self.runs.values(), key=lambda r: r["created_at"], reverse=True)
        runs = [r for r in runs if status is None or r["status"] == status]
        fields = RunSummary.model_fields
        return [RunSummary.model_validate({k: r[k] for k in fields}) for r in runs[offset:][:limit]]
