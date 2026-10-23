"""API REST do agente (T21): aceita o lead, roda o grafo em background e serve a auditoria.

Rotas (`docs/00-arquitetura.md`, seção 7):
- `POST /v1/leads/qualify` → 202 com `run_id` (o grafo roda em background, `app/api/runner.py`);
- `GET /v1/runs/{run_id}` → status, resultado, justificativa, custo e ids do CRM;
- `GET /v1/runs?status=...` → listagem (fila de revisão com `status=needs_review`);
- `GET /health` → Postgres e MCP (obrigatórios) e Ollama (informativo), sem detalhe de erro.

Controles: `X-API-Key` comparada em tempo constante em todo `/v1`; corpo limitado (413);
`LeadInput` com `extra="forbid"`; erros de validação sem ecoar o valor enviado (o texto do
lead pode ser injeção ou dado pessoal); fila limitada (429); `/docs` desligado em produção.
"""

import asyncio
import hmac
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.runner import QueueFullError, RunQueue, RunStore
from app.audit.repository import RunSummary
from app.config import Settings
from app.schemas import LeadInput

HealthCheck = Callable[[], Awaitable[None]]
HEALTH_TIMEOUT_S = 3.0
REQUIRED_CHECKS = ("postgres", "mcp")
RETRY_AFTER_S = 60
MAX_VALIDATION_ERRORS = 10
RunStatus = Literal["running", "completed", "failed", "needs_review", "rejected"]


@dataclass
class Services:
    store: RunStore
    queue: RunQueue
    checks: Mapping[str, HealthCheck] = field(default_factory=dict)


def get_services(request: Request) -> Services:
    built: Services = request.app.state.services
    return built


ServicesDep = Annotated[Services, Depends(get_services)]


# --- contratos da API ----------------------------------------------------------------------


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


class RunList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[RunSummary]
    limit: int
    offset: int


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "degraded"]
    checks: dict[str, Literal["ok", "fail"]]


# --- middleware ----------------------------------------------------------------------------


class BodyLimit:
    """Recusa corpo acima do limite (413), pelo `Content-Length` ou contando o que chega.

    O corpo é lido inteiro (no máximo `max_bytes`) antes de chegar ao app e depois repassado:
    assim um envio sem `Content-Length` (chunked) também recebe 413, e não um erro genérico.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self._max):
            await _send_413(send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self._max:
                await _send_413(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self._app(scope, replay, send)


async def _send_413(send: Send) -> None:
    body = b'{"detail":"corpo da requisicao acima do limite"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


# --- app -----------------------------------------------------------------------------------


def create_app(
    settings: Settings,
    services: Services | None = None,
    *,
    build_services: Callable[[Settings], Any] | None = None,
) -> FastAPI:
    """`services` injeta dependências prontas (testes); `build_services` monta as de produção.

    `build_services(settings)` é um context manager assíncrono que entrega `Services`.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            app.state.services = services
            try:
                yield
            finally:
                await services.queue.shutdown()
            return
        if build_services is None:  # pragma: no cover - erro de montagem, não de uso
            raise RuntimeError("create_app precisa de `services` ou `build_services`")
        async with build_services(settings) as built:
            app.state.services = built
            try:
                yield
            finally:
                await built.queue.shutdown()

    docs = settings.app_env != "prod"
    app = FastAPI(
        title="Lead Qualifier · FrotaSense",
        version="0.1.0",
        summary="Qualificação de leads B2B: o LLM extrai e justifica, o código pontua.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    expected_key = settings.api_key.get_secret_value().encode()
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def require_api_key(key: Annotated[str | None, Depends(api_key_header)]) -> None:
        if key is None or not hmac.compare_digest(key.encode(), expected_key):
            raise HTTPException(
                status_code=401,
                detail="chave de API ausente ou inválida",
                headers={"WWW-Authenticate": "ApiKey"},
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Só o local e o tipo: a mensagem padrão ecoa o valor enviado (injeção, e-mail...).
        errors = [
            {"loc": [str(part) for part in err.get("loc", ())], "type": err.get("type")}
            for err in exc.errors()[:MAX_VALIDATION_ERRORS]
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

    @v1.post(
        "/leads/qualify",
        status_code=202,
        response_model=QualifyAccepted,
        responses={401: {}, 413: {}, 422: {}, 429: {}},
    )
    async def qualify(lead: LeadInput, response: Response, svc: ServicesDep) -> QualifyAccepted:
        """Aceita o lead e qualifica em background. Acompanhe por `GET /v1/runs/{run_id}`."""
        try:
            run_id = await svc.queue.submit(lead)
        except QueueFullError:
            raise HTTPException(
                status_code=429,
                detail="fila de qualificação cheia; tente mais tarde",
                headers={"Retry-After": str(RETRY_AFTER_S)},
            ) from None
        url = f"/v1/runs/{run_id}"
        response.headers["Location"] = url
        return QualifyAccepted(run_id=run_id, status_url=url)

    @v1.get("/runs/{run_id}", response_model=RunOut, responses={401: {}, 404: {}})
    async def get_run(run_id: uuid.UUID, svc: ServicesDep) -> RunOut:
        """Status, resultado (tier, score, critérios, justificativa), custo e ids do CRM."""
        run = await svc.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="execução não encontrada")
        return RunOut.model_validate(run.model_dump(exclude={"lead_input", "steps", "next_step"}))

    @v1.get("/runs", response_model=RunList, responses={401: {}})
    async def list_runs(
        svc: ServicesDep,
        status: RunStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    ) -> RunList:
        """Execuções mais recentes primeiro. `status=needs_review` é a fila de revisão humana."""
        items = await svc.store.list_runs(status=status, limit=limit, offset=offset)
        return RunList(items=items, limit=limit, offset=offset)

    app.include_router(v1)

    @app.get("/health", response_model=Health, responses={503: {"model": Health}})
    async def health(svc: ServicesDep, response: Response) -> Health:
        """Postgres e MCP decidem o status; Ollama é informativo (entra no grafo na T28)."""
        names = list(svc.checks)
        outcomes = await asyncio.gather(
            *(asyncio.wait_for(svc.checks[n](), HEALTH_TIMEOUT_S) for n in names),
            return_exceptions=True,
        )
        checks: dict[str, Literal["ok", "fail"]] = {
            n: "fail" if isinstance(o, BaseException) else "ok"
            for n, o in zip(names, outcomes, strict=True)
        }
        ok = all(checks.get(n) == "ok" for n in REQUIRED_CHECKS if n in checks)
        if not ok:
            response.status_code = 503
        return Health(status="ok" if ok else "degraded", checks=checks)

    app.add_middleware(BodyLimit, max_bytes=settings.api_max_body_bytes)
    return app
