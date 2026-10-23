"""Fila das qualificações aceitas pela API (T21): o POST responde 202 e o grafo roda depois.

Garantias:
- a execução é criada como `running` **antes** do 202, então o `GET` já a encontra;
- fila limitada (ASI08): no máximo `max_pending` execuções aceitas e não terminadas, e
  `max_concurrent` rodando ao mesmo tempo (plano gratuito da Groq). Fila cheia → `QueueFullError`;
- uma execução nunca fica `running` para sempre: exceção, cancelamento ou falha ao gravar o
  resultado viram `failed`, com mensagem genérica (o detalhe não sai da API).
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from typing import Protocol

from app.audit.repository import RunSummary, RunView
from app.schemas import LeadInput

logger = logging.getLogger(__name__)


class RunStore(Protocol):
    """O que a API usa do `AuditRepository`."""

    async def start_run(
        self, lead: LeadInput, prompt_version: str, run_id: uuid.UUID | None = None
    ) -> uuid.UUID: ...

    async def fail_run(self, run_id: uuid.UUID, errors: Sequence[str], latency_ms: int) -> None: ...

    async def get_run(self, run_id: uuid.UUID) -> RunView | None: ...

    async def list_runs(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[RunSummary]: ...


class Executor(Protocol):
    """Roda o grafo para uma execução já criada (produção: `app/api/production.py`)."""

    async def __call__(self, run_id: uuid.UUID, lead: LeadInput) -> None: ...


class QueueFullError(Exception):
    """Fila no limite: a API responde 429."""


class RunQueue:
    def __init__(
        self,
        store: RunStore,
        executor: Executor,
        *,
        prompt_version: str,
        max_concurrent: int = 1,
        max_pending: int = 10,
    ) -> None:
        self._store = store
        self._executor = executor
        self._prompt_version = prompt_version
        self._slots = asyncio.Semaphore(max_concurrent)
        self._max_pending = max_pending
        self._tasks: set[asyncio.Task[None]] = set()
        self._starting = 0  # reservas feitas antes do `await start_run` (evita corrida)

    @property
    def pending(self) -> int:
        return len(self._tasks) + self._starting

    async def submit(self, lead: LeadInput) -> uuid.UUID:
        if self.pending >= self._max_pending:
            raise QueueFullError
        self._starting += 1
        try:
            run_id = await self._store.start_run(lead, self._prompt_version, uuid.uuid4())
            task = asyncio.create_task(self._run(run_id, lead), name=f"run-{run_id}")
        finally:
            self._starting -= 1
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def _run(self, run_id: uuid.UUID, lead: LeadInput) -> None:
        started = time.monotonic()
        try:
            async with self._slots:
                await self._executor(run_id, lead)
        except asyncio.CancelledError:
            await self._fail(run_id, "execução interrompida (API encerrada)", started)
            raise
        except Exception as exc:
            logger.exception("execução %s falhou", run_id)
            await self._fail(run_id, f"falha interna ({type(exc).__name__})", started)
            return
        run = await self._store.get_run(run_id)
        if run is not None and run.status == "running":
            # O grafo terminou, mas o `audit_log` não conseguiu gravar o resultado.
            await self._fail(run_id, "execução terminou sem gravar o resultado", started)

    async def _fail(self, run_id: uuid.UUID, message: str, started: float) -> None:
        try:
            latency = round((time.monotonic() - started) * 1000)
            await self._store.fail_run(run_id, [message], latency)
        except Exception:
            logger.exception("não foi possível marcar a execução %s como falha", run_id)

    async def shutdown(self) -> None:
        """Cancela o que está na fila; cada execução cancelada fica `failed`."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
