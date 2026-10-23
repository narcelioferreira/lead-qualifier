"""Demo offline (T22): a API e o grafo reais, sem rede, com respostas gravadas.

Para quem não clona o repositório: o workflow `Demo offline` (GitHub Actions, disparo manual)
roda este módulo e publica o resultado no *Job Summary*. Nada ali chama API externa:
- a **gravação** (`--record`, feita uma vez pelo autor) roda o grafo de verdade com a Groq e o
  servidor MCP (Tavily e sites) em leads do split **dev** e salva as respostas em
  `evals/demo/cassette.json`;
- a **reprodução** (padrão) sobe a API FastAPI em processo, com o grafo real (rubrica, regras,
  detector de injeção, saneamento) e a auditoria em memória, e devolve as respostas gravadas no
  lugar da Groq, da Tavily e dos sites. Um audit hook do Python bloqueia qualquer conexão de rede
  fora do loopback, então a demo prova que roda offline.

Uso: `python -m evals.demo [--summary ARQUIVO]` · `python -m evals.demo --record`.
"""

import argparse
import asyncio
import dataclasses
import html
import ipaddress
import re
import secrets
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.main import Services, create_app
from app.api.runner import RunQueue
from app.audit.memory import MemoryAuditRepository
from app.config import Settings, get_settings
from app.graph.builder import build_graph
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.llm.base import LLMResult, LLMUnavailableError, Message, StructuredLLM
from app.routing.cost import ModelSpec, Usage
from app.schemas import LeadInput
from evals.dataset import DATASET_PATH, DatasetItem, load_dataset
from evals.labels import LABELS_PATH, FinalLabel, load_jsonl
from tools_mcp.base import ToolUnavailableError
from tools_mcp.search import SearchResult
from tools_mcp.site import SiteContent

CASSETTE_PATH = DATASET_PATH.parent / "demo" / "cassette.json"
# Um lead por tier no gabarito humano, mais os dois ataques do dev (injeção e spam).
DEMO_LEADS = ("L024", "L002", "L030", "L005", "L020")
PROMPT_VERSION = "v2"
RATIONALE_CHARS = 700
POLL_S = 0.02
# Minimização (LGPD): e-mails do conteúdo público gravado não vão para o repositório.
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
EMAIL_MASK = "[e-mail removido]"


# --- fita gravada ----------------------------------------------------------------------------


class LLMCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str
    parsed: dict[str, Any]
    usage: Usage
    model_key: str
    model: str
    latency_ms: float = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)


class LeadTape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str
    searches: list[SearchResult] = Field(default_factory=list)
    sites: list[SiteContent] = Field(default_factory=list)
    llm: list[LLMCall] = Field(default_factory=list)


class Cassette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recorded_at: datetime
    prompt_version: str
    config_digest: str | None
    leads: dict[str, LeadTape]


def redact(text: str) -> str:
    return _EMAIL.sub(EMAIL_MASK, text)


def save_cassette(cassette: Cassette, path: Path = CASSETTE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = redact(cassette.model_dump_json(indent=2))
    Cassette.model_validate_json(text)  # a fita mascarada continua válida
    path.write_text(text + "\n", encoding="utf-8")


def load_cassette(path: Path = CASSETTE_PATH) -> Cassette:
    return Cassette.model_validate_json(path.read_text(encoding="utf-8"))


class ReplayLLM:
    """Devolve as respostas gravadas, na ordem. Fita esgotada ou fora de ordem → erro do LLM."""

    def __init__(self, tape: LeadTape) -> None:
        self._calls = list(tape.llm)

    async def structured[T: BaseModel](
        self, spec: ModelSpec, messages: Sequence[Message], schema: type[T]
    ) -> LLMResult[T]:
        if not self._calls or self._calls[0].schema_name != schema.__name__:
            raise LLMUnavailableError(f"demo: sem resposta gravada para {schema.__name__}")
        call = self._calls.pop(0)
        return LLMResult(
            parsed=schema.model_validate(call.parsed),
            usage=call.usage,
            model_key=call.model_key,
            model=call.model,
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
            attempts=1,
        )


class ReplayTools:
    def __init__(self, tape: LeadTape) -> None:
        self._searches = list(tape.searches)
        self._sites = list(tape.sites)

    async def search(self, query: str) -> SearchResult:
        if not self._searches:
            raise ToolUnavailableError("demo: sem busca gravada")
        return self._searches.pop(0)

    async def fetch(self, domain: str) -> SiteContent:
        if not self._sites:
            raise ToolUnavailableError("demo: sem site gravado")
        return self._sites.pop(0)


class RecordingLLM:
    def __init__(self, inner: StructuredLLM, tape: LeadTape) -> None:
        self._inner = inner
        self._tape = tape

    async def structured[T: BaseModel](
        self, spec: ModelSpec, messages: Sequence[Message], schema: type[T]
    ) -> LLMResult[T]:
        result = await self._inner.structured(spec, messages, schema)
        self._tape.llm.append(
            LLMCall(
                schema_name=schema.__name__,
                parsed=result.parsed.model_dump(mode="json"),
                usage=result.usage,
                model_key=result.model_key,
                model=result.model,
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
            )
        )
        return result


class RecordingTools:
    def __init__(self, search: Any, site: Any, tape: LeadTape) -> None:
        self._search = search
        self._site = site
        self._tape = tape

    async def search(self, query: str) -> SearchResult:
        result: SearchResult = await self._search.search(query)
        self._tape.searches.append(result)
        return result

    async def fetch(self, domain: str) -> SiteContent:
        result: SiteContent = await self._site.fetch(domain)
        self._tape.sites.append(result)
        return result


def demo_items() -> list[DatasetItem]:
    items = {item.id: item for item in load_dataset()}
    chosen = [items[i] for i in DEMO_LEADS]
    # O split test é reservado às avaliações (T16+): a demo nunca grava nem mostra um lead dele.
    if any(item.split != "dev" for item in chosen):
        raise ValueError("a demo só usa leads do split dev")
    return chosen


async def record(path: Path = CASSETTE_PATH) -> Cassette:
    """Roda o grafo real (Groq + MCP) nos leads da demo e grava as respostas. Sem CRM."""
    from app.graph.runtime import production_deps

    tapes: dict[str, LeadTape] = {}
    async with production_deps(get_settings(), prompt_version=PROMPT_VERSION) as deps:
        for item in demo_items():
            tape = LeadTape(lead_id=item.id)
            tools = RecordingTools(deps.search, deps.site, tape)
            recorded = dataclasses.replace(
                deps, llm=RecordingLLM(deps.llm, tape), search=tools, site=tools
            )
            raw = item.to_lead_input().model_dump(mode="json")
            await build_graph(make_nodes(recorded)).ainvoke(
                {"run_id": str(uuid.uuid4()), "raw_input": raw}
            )
            tapes[item.id] = tape
            print(f"{item.id}: {len(tape.llm)} chamadas ao LLM, {len(tape.searches)} buscas")
        digest = deps.config_digest
    cassette = Cassette(
        recorded_at=datetime.now(UTC),
        prompt_version=PROMPT_VERSION,
        config_digest=digest,
        leads=tapes,
    )
    save_cassette(cassette, path)
    return cassette


# --- reprodução pela API -----------------------------------------------------------------------


class DemoRun(BaseModel):
    lead_id: str
    company: str
    label: str | None
    accepted_status: int
    run: dict[str, Any]


class DemoReport(BaseModel):
    cassette: Cassette
    no_key_status: int
    forged_tier_status: int
    forged_tier_errors: list[dict[str, Any]]
    runs: list[DemoRun]


@dataclasses.dataclass
class _Demo:
    client: httpx.AsyncClient
    key: str


async def _demo_api(cassette: Cassette) -> AsyncIterator[_Demo]:
    items = {item.to_lead_input().company_name: item.id for item in demo_items()}
    store = MemoryAuditRepository()

    async def execute(run_id: uuid.UUID, lead: LeadInput) -> None:
        tape = cassette.leads[items[lead.company_name]]
        tools = ReplayTools(tape)
        deps = MvpDeps(
            llm=ReplayLLM(tape),
            search=tools,
            site=tools,
            audit=store,  # type: ignore[arg-type]  # mesmo contrato, sem banco
            prompt_version=cassette.prompt_version,
            config_digest=cassette.config_digest,
        )
        raw = lead.model_dump(mode="json")
        await build_graph(make_nodes(deps)).ainvoke({"run_id": str(run_id), "raw_input": raw})

    key = secrets.token_urlsafe(32)  # gerada a cada execução: nenhum segredo no repositório
    settings = Settings(
        _env_file=None,
        api_key=SecretStr(key),
        database_url=SecretStr("postgresql+psycopg://demo@127.0.0.1:1/demo"),
    )
    queue = RunQueue(store, execute, prompt_version=cassette.prompt_version)
    app = create_app(settings, Services(store=store, queue=queue))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://demo.local") as client:
            yield _Demo(client=client, key=key)


async def run_demo(cassette: Cassette) -> DemoReport:
    labels = {row.id: row.tier.value for row in load_jsonl(LABELS_PATH, FinalLabel)}
    async for demo in _demo_api(cassette):
        client, auth = demo.client, {"X-API-Key": demo.key}
        first = demo_items()[0].to_lead_input().model_dump(mode="json")
        no_key = await client.post("/v1/leads/qualify", json=first)
        forged = await client.post("/v1/leads/qualify", json=first | {"tier": "A"}, headers=auth)
        runs: list[DemoRun] = []
        for item in demo_items():
            lead = item.to_lead_input()
            accepted = await client.post(
                "/v1/leads/qualify", json=lead.model_dump(mode="json"), headers=auth
            )
            url = accepted.json()["status_url"]
            for _ in range(500):
                run: dict[str, Any] = (await client.get(url, headers=auth)).json()
                if run["status"] != "running":
                    break
                await asyncio.sleep(POLL_S)
            runs.append(
                DemoRun(
                    lead_id=item.id,
                    company=lead.company_name,
                    label=labels.get(item.id),
                    accepted_status=accepted.status_code,
                    run=run,
                )
            )
        return DemoReport(
            cassette=cassette,
            no_key_status=no_key.status_code,
            forged_tier_status=forged.status_code,
            forged_tier_errors=forged.json()["detail"],
            runs=runs,
        )
    raise RuntimeError("a API da demo não subiu")  # pragma: no cover


# --- relatório ---------------------------------------------------------------------------------


def _md(text: str) -> str:
    """Texto do LLM ou do lead no Markdown: sem HTML e sem quebrar a tabela."""
    return html.escape(" ".join(str(text).split()), quote=False).replace("|", "\\|")


def render(report: DemoReport) -> str:
    tape = report.cassette
    lines = [
        "# Demo offline · Lead Qualifier (FrotaSense)",
        "",
        "API FastAPI e grafo LangGraph **reais**, rodando **sem rede**: as respostas da Groq, da "
        "Tavily e dos sites foram gravadas uma vez pelo autor "
        f"({tape.recorded_at:%d/%m/%Y}, prompt `{tape.prompt_version}`) e são reproduzidas "
        "aqui. Rubrica, regras eliminatórias, detector de injeção e saneamento rodam de verdade. "
        "*O LLM extrai e justifica; o código pontua.*",
        "",
        "## Segurança da API",
        "",
        "| Tentativa | Resposta |",
        "|---|---|",
        f"| `POST /v1/leads/qualify` sem `X-API-Key` | **{report.no_key_status}** |",
        f'| Lead com `"tier": "A"` (o cliente tenta decidir o tier) | '
        f"**{report.forged_tier_status}** "
        f"`{', '.join(str(e['type']) for e in report.forged_tier_errors)}` |",
        "",
        "## Resultado por lead",
        "",
        "| Lead | Empresa | Rótulo humano | Tier do agente | Score | Status | Regras e tetos |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in report.runs:
        run, result = item.run, item.run.get("result") or {}
        rules = ", ".join([*result.get("disqualifiers", []), *result.get("caps_applied", [])])
        lines.append(
            f"| {item.lead_id} | {_md(item.company)} | {item.label or '—'} | "
            f"**{run.get('tier') or '—'}** | {run.get('score') or '—'} | {run['status']} | "
            f"{rules or '—'} |"
        )
    hits = sum(1 for item in report.runs if item.label and item.label == item.run.get("tier"))
    lines += ["", f"Concordância com o rótulo humano nesta amostra: **{hits}/{len(report.runs)}**."]
    for item in report.runs:
        result = item.run.get("result") or {}
        lines += ["", f"### {item.lead_id} · {_md(item.company)}", ""]
        criteria = result.get("criteria", [])
        if criteria:
            lines += ["| Critério | Valor | Pontos |", "|---|---|---|"]
            lines += [
                f"| {c['criterion']} | {_md(c['value'])} | {c['points']:g}/{c['max_points']:g} |"
                for c in criteria
            ]
        rationale = _md(result.get("rationale") or "; ".join(item.run.get("errors", [])))
        if len(rationale) > RATIONALE_CHARS:
            rationale = rationale[: RATIONALE_CHARS - 1] + "…"
        lines += ["", f"> {rationale}"]
    return "\n".join(lines) + "\n"


# --- guarda de rede ----------------------------------------------------------------------------


def _is_loopback(address: Any) -> bool:
    host = address[0] if isinstance(address, tuple) and address else address
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def _network_guard(event: str, args: tuple[Any, ...]) -> None:
    if event == "socket.connect" and not _is_loopback(args[1]):
        raise PermissionError(f"demo offline: conexão de rede bloqueada ({args[1]!r})")
    if event == "socket.getaddrinfo" and args[0] != "localhost" and not _is_loopback(args[0]):
        raise PermissionError(f"demo offline: resolução de nome bloqueada ({args[0]!r})")


def install_network_guard() -> None:
    """Audit hook (PEP 578): não dá para remover, por isso só a CLI instala."""
    sys.addaudithook(_network_guard)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="grava a fita (Groq + MCP reais)")
    parser.add_argument("--summary", type=Path, help="acrescenta o relatório neste arquivo")
    args = parser.parse_args(argv)
    if args.record:
        asyncio.run(record())
        print(f"fita gravada em {CASSETTE_PATH}")
        return 0
    cassette = load_cassette()
    install_network_guard()
    text = render(asyncio.run(run_demo(cassette)))
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
