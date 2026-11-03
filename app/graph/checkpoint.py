"""Checkpointer do grafo (T31): o state de uma execução parada na revisão humana fica no Postgres.

- **Desserialização restrita:** o serializador padrão do LangGraph importa e instancia qualquer
  classe gravada no checkpoint (quem escreve na tabela poderia executar código ao carregar).
  Aqui só os tipos do state são aceitos (`STATE_TYPES`); um tipo fora da lista não é
  instanciado. Teste: `tests/graph/test_review.py`.
- **Retenção mínima:** o checkpoint tem o lead completo (e-mail sem máscara, mensagem). A
  execução que termina sem parar tem o checkpoint apagado (`forget`); só fica o de quem
  espera a decisão humana, até ela chegar.
- O `thread_id` é o `run_id` da execução: o `POST /v1/runs/{id}/review` acha o state por ele.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from app.audit.repository import StepRecord
from app.ontology import models as ontology
from app.ontology.scoring import ScoreResult
from app.routing.cost import Usage
from app.schemas import (
    CriterionScore,
    Evidence,
    EvidenceSource,
    HumanReview,
    LeadInput,
    LeadSource,
    NextStep,
    QualificationResult,
    Tier,
)
from app.security.guardrail import GuardrailVerdict
from tools_mcp.kb import KBHit

# Tipos que aparecem no state (`app/graph/state.py`). Tipo novo no state entra aqui; o teste
# de ida e volta do checkpoint falha se faltar algum.
STATE_TYPES: tuple[type, ...] = (
    LeadInput,
    LeadSource,
    Evidence,
    EvidenceSource,
    CriterionScore,
    NextStep,
    QualificationResult,
    HumanReview,
    Tier,
    StepRecord,
    Usage,
    ScoreResult,
    GuardrailVerdict,
    KBHit,
    ontology.LeadProfile,
    ontology.SectorFit,
    ontology.SizeBand,
    ontology.RegionFit,
    ontology.CompanyKind,
    ontology.Area,
    ontology.Seniority,
    ontology.BuyingRole,
    ontology.IntentSignal,
    ontology.LeadFlag,
    ontology.Certainty,
    ontology.Criterion,
)
SERIALIZER = JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)
POOL_SIZE = 4  # = API_MAX_CONCURRENT_RUNS máximo


def thread_config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}}


def conninfo(database_url: SecretStr) -> str:
    """URL do SQLAlchemy (`postgresql+psycopg://`) → conninfo do psycopg (`postgresql://`)."""
    return database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(database_url: SecretStr) -> AsyncIterator[AsyncPostgresSaver]:
    """Checkpointer com pool próprio; cria ou migra as tabelas do LangGraph (idempotente)."""
    kwargs: dict[str, Any] = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    async with AsyncConnectionPool(
        conninfo(database_url), min_size=1, max_size=POOL_SIZE, kwargs=kwargs, open=False
    ) as pool:
        saver = AsyncPostgresSaver(pool, serde=SERIALIZER)  # type: ignore[arg-type]
        await saver.setup()
        yield saver


async def forget(saver: BaseCheckpointSaver[str], run_id: str) -> None:
    """Apaga o checkpoint da execução (retenção mínima: o state tem dados pessoais)."""
    await saver.adelete_thread(run_id)
