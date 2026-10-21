"""Repositório de auditoria contra o Postgres real (`docker compose up -d postgres`).

Cada execução cria um banco descartável no mesmo servidor, aplica as migrations, roda os testes
e apaga o banco no fim: o banco de desenvolvimento nunca é tocado.
"""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.audit.db import create_engine as create_async_engine
from app.audit.db import session_factory
from app.audit.repository import AuditError, AuditRepository, StepRecord
from app.routing.cost import Usage
from app.schemas import (
    CriterionScore,
    LeadInput,
    NextStep,
    QualificationResult,
    Tier,
)
from tests.integration.conftest import alembic_config

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ROOT = Path(__file__).resolve().parents[2]

LEAD = LeadInput(
    company_name="Gobor Transportes",
    company_domain="gobor.com.br",
    contact_role="Diretor de Operações",
    contact_email="lead-001@example.com",
    message="Queremos proposta para 85 caminhões.",
    source="demo_request",
)


@pytest.fixture
async def repo(migrated: str) -> AsyncIterator[AuditRepository]:
    engine = create_async_engine(SecretStr(migrated))
    yield AuditRepository(session_factory(engine))
    await engine.dispose()


def _result(run_id: uuid.UUID, needs_review: bool = False) -> QualificationResult:
    return QualificationResult(
        run_id=str(run_id),
        tier=Tier.A,
        score=100.0,
        is_borderline=False,
        confidence=0.92,
        needs_human_review=needs_review,
        criteria=[
            CriterionScore(criterion="sector", value="target", points=30, max_points=30),
        ],
        next_step=NextStep(action="Agendar demo com AE", owner="AE", sla_hours=24),
        rationale="Transportadora alvo com pedido de proposta.",
        prompt_version="v1",
        cost_usd=0.0000562,
    )


def _step(node: str, cost: str, cached: int = 0) -> StepRecord:
    return StepRecord(
        node=node,
        model_key="groq-mini",
        model="openai/gpt-oss-20b",
        route_reason="padrão",
        usage=Usage(input_tokens=159, cached_input_tokens=cached, output_tokens=54),
        cost_usd=Decimal(cost),
        latency_ms=543,
        output={"sector": "target"},
        sources=["https://gobor.com.br"],
    )


async def test_full_run_is_written_and_read_back(repo: AuditRepository) -> None:
    run_id = await repo.start_run(LEAD, "v1")
    await repo.add_step(run_id, StepRecord(node="validate_input"))
    await repo.add_step(run_id, _step("normalize", "0.0000281", cached=100))
    await repo.add_step(run_id, _step("assess_criteria", "0.0000281"))
    await repo.complete_run(run_id, _result(run_id), latency_ms=1800, crm_ids={"company": "123"})

    run = await repo.get_run(run_id)
    assert run is not None
    assert run.status == "completed"
    assert (run.tier, run.score, run.confidence) == ("A", Decimal("100.0"), Decimal("0.920"))
    assert run.cost_usd == Decimal("0.0000562")  # soma dos passos, calculada no banco
    assert run.latency_ms == 1800
    assert run.finished_at is not None and run.finished_at >= run.created_at
    assert run.crm_ids == {"company": "123"}
    assert run.next_step is not None and run.next_step["owner"] == "AE"
    assert run.result is not None and run.result["rationale"].startswith("Transportadora")
    # Minimização: o e-mail do lead não é gravado em claro.
    assert run.lead_input["contact_email"] == "l***@example.com"
    assert "lead-001" not in str(run.model_dump())
    assert [s.node for s in run.steps] == ["validate_input", "normalize", "assess_criteria"]
    assert run.steps[1].usage.cached_input_tokens == 100
    assert run.steps[1].sources == ["https://gobor.com.br"]


async def test_needs_review_status(repo: AuditRepository) -> None:
    run_id = await repo.start_run(LEAD, "v1")
    await repo.complete_run(run_id, _result(run_id, needs_review=True), latency_ms=10)
    run = await repo.get_run(run_id)
    assert run is not None and run.status == "needs_review"
    assert run.cost_usd == 0


async def test_failed_run_keeps_truncated_errors(repo: AuditRepository) -> None:
    run_id = await repo.start_run(LEAD, "v1")
    await repo.add_step(run_id, _step("research", "0.00001"))
    await repo.fail_run(run_id, ["groq: indisponível após 3 tentativas", "x" * 5000], latency_ms=99)
    run = await repo.get_run(run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.errors[0].startswith("groq")
    assert len(run.errors[1]) == 500
    assert run.cost_usd == Decimal("0.00001")  # o custo gasto antes da falha é registrado


async def test_closed_run_cannot_be_changed(repo: AuditRepository) -> None:
    run_id = await repo.start_run(LEAD, "v1")
    await repo.complete_run(run_id, _result(run_id), latency_ms=5)
    with pytest.raises(AuditError, match="já foi encerrada"):
        await repo.add_step(run_id, StepRecord(node="tarde_demais"))
    with pytest.raises(AuditError, match="já foi encerrada"):
        await repo.fail_run(run_id, ["x"], latency_ms=1)


async def test_unknown_and_mismatched_runs(repo: AuditRepository) -> None:
    missing = uuid.uuid4()
    assert await repo.get_run(missing) is None
    with pytest.raises(AuditError, match="não existe"):
        await repo.add_step(missing, StepRecord(node="x"))
    run_id = await repo.start_run(LEAD, "v1")
    with pytest.raises(AuditError, match="não confere"):
        await repo.complete_run(run_id, _result(uuid.uuid4()), latency_ms=1)


async def test_duplicate_run_id_is_rejected(repo: AuditRepository) -> None:
    run_id = await repo.start_run(LEAD, "v1")
    with pytest.raises(IntegrityError):
        await repo.start_run(LEAD, "v1", run_id=run_id)


def test_database_constraints_and_cascade(migrated: str) -> None:
    engine = create_engine(migrated, hide_parameters=True)
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (run_id, prompt_version, lead_input)"
                " VALUES (:r, 'v1', '{}')"
            ),
            {"r": run_id},
        )
        conn.execute(text("INSERT INTO agent_steps (run_id, node) VALUES (:r, 'n')"), {"r": run_id})
    bad = [
        "UPDATE agent_runs SET tier = 'E' WHERE run_id = :r",
        "UPDATE agent_runs SET status = 'hacked' WHERE run_id = :r",
        "UPDATE agent_runs SET score = 101 WHERE run_id = :r",
        "UPDATE agent_steps SET cached_input_tokens = 5 WHERE run_id = :r",
        "UPDATE agent_steps SET cost_usd = -1 WHERE run_id = :r",
    ]
    for sql in bad:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(sql), {"r": run_id})
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs WHERE run_id = :r"), {"r": run_id})
        left = conn.execute(
            text("SELECT count(*) FROM agent_steps WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    assert left == 0
    engine.dispose()


def test_models_match_migrations(migrated: str) -> None:
    command.check(alembic_config(migrated))  # falha se o modelo divergir do schema migrado


def test_downgrade_and_upgrade_again(migrated: str) -> None:
    config = alembic_config(migrated)
    engine = create_engine(migrated)
    command.downgrade(config, "base")
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        has_vector = conn.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
    assert not {"agent_runs", "agent_steps"} & tables
    assert has_vector == 0
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert {"agent_runs", "agent_steps"} <= set(inspect(conn).get_table_names())
    engine.dispose()


async def test_record_run_writes_complete_run_in_one_call(repo: AuditRepository) -> None:
    run_id = uuid.uuid4()
    await repo.record_run(
        run_id=run_id,
        prompt_version="v1",
        lead=LEAD,
        status="completed",
        steps=[StepRecord(node="validate_input"), _step("normalize", "0.0002"),
               _step("assess", "0.0001")],
        result=_result(run_id),
        errors=["site: home: HTTP 404"],
        latency_ms=1234,
    )  # fmt: skip
    run = await repo.get_run(run_id)
    assert run is not None
    assert (run.status, run.tier, run.cost_usd) == ("completed", "A", Decimal("0.0003"))
    assert run.errors == ["site: home: HTTP 404"]
    assert [s.node for s in run.steps] == ["validate_input", "normalize", "assess"]
    assert run.lead_input["contact_email"] == "l***@example.com"


async def test_record_run_rejected_keeps_only_field_names(repo: AuditRepository) -> None:
    run_id = uuid.uuid4()
    await repo.record_run(
        run_id=run_id,
        prompt_version="v1",
        lead=None,
        status="rejected",
        steps=[StepRecord(node="validate_input")],
        errors=["entrada inválida: tier: extra_forbidden"],
        latency_ms=3,
        rejected_fields=["tier", "company_name", "message"],
    )
    run = await repo.get_run(run_id)
    assert run is not None and run.status == "rejected"
    assert run.lead_input == {"rejected": True, "fields": ["company_name", "message", "tier"]}
    assert run.tier is None and run.result is None
