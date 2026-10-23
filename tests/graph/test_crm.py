"""Grafo consumindo o servidor MCP (in-process, HTTP mockado) e o nó `write_to_crm` (T20)."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
import respx
from mcp.client.client import Client

from app.graph.builder import build_graph
from app.graph.nodes.crm import make_write_to_crm, note_text
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.graph.state import QualificationState
from app.mcp_client import LeadTools, NoteCreated
from tests.graph.test_mvp import ASSESSMENT, LEAD, FakeAudit, FakeLLM, extraction
from tests.unit.test_mcp_client import tool_deps
from tools_mcp.base import ToolRequestError
from tools_mcp.hubspot import CompanyProps, ContactProps, UpsertResult
from tools_mcp.hubspot_http import HUBSPOT_URL
from tools_mcp.search import TAVILY_URL
from tools_mcp.server import build_server

pytestmark = pytest.mark.anyio

MCP_LEAD = LEAD | {"company_domain": "serraazultransportes.example"}
EMAIL = LEAD["contact_email"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _llm() -> FakeLLM:
    return FakeLLM({Extraction: [extraction()], Assessment: [ASSESSMENT]})


def _mock_apis(router: respx.Router) -> dict[str, respx.Route]:
    router.post(TAVILY_URL).respond(
        200, json={"results": [{"title": "Serra Azul", "url": "https://x.com.br/", "content": "y"}]}
    )
    hub = f"{HUBSPOT_URL}/crm"
    router.post(f"{hub}/v3/objects/companies/search").respond(200, json={"results": []})
    return {
        "company": router.post(f"{hub}/v3/objects/companies/batch/upsert").respond(
            200, json={"results": [{"id": "111", "new": True}]}
        ),
        "contact": router.post(f"{hub}/v3/objects/contacts/batch/upsert").respond(
            200, json={"results": [{"id": "333", "new": True}]}
        ),
        "assoc": router.put(
            f"{hub}/v4/objects/contacts/333/associations/default/companies/111"
        ).respond(200, json={}),
        "note": router.post(f"{hub}/v3/objects/notes").respond(201, json={"id": "444"}),
    }


async def test_grafo_pelo_mcp_grava_no_crm_de_ponta_a_ponta() -> None:
    audit = FakeAudit()
    run_id = str(uuid.uuid4())
    with respx.mock(assert_all_called=True) as router:
        routes = _mock_apis(router)
        async with Client(build_server(tool_deps())) as client:
            tools = LeadTools(client)
            deps = MvpDeps(llm=_llm(), search=tools, site=tools, crm=tools, audit=audit)  # type: ignore[arg-type]
            state: QualificationState = await build_graph(make_nodes(deps)).ainvoke(
                {"run_id": run_id, "raw_input": MCP_LEAD}
            )

    assert state["status"] == "completed", state.get("errors")
    assert state["crm"] == {"company_id": "111", "contact_id": "333", "note_id": "444"}
    assert any(e.source_type.value == "company_site" for e in state["evidence"])  # fixture via MCP

    company = json.loads(routes["company"].calls[0].request.content)["inputs"][0]["properties"]
    assert company["ai_fit_tier"] == state["result"].tier.value
    assert company["ai_run_id"] == run_id
    note = json.loads(routes["note"].calls[0].request.content)["properties"]["hs_note_body"]
    assert "Critérios:" in note and "Setor:" in note and run_id in note
    step = next(s for s in audit.records[0]["steps"] if s.node == "write_to_crm")
    assert step.output["note_id"] == "444" and step.output["note_created"] is True


async def test_mesmo_run_id_duas_vezes_nao_duplica_a_note() -> None:
    """Retry do grafo com o mesmo `run_id`: upserts atualizam e a Note não se repete."""
    run_id = str(uuid.uuid4())
    with respx.mock as router:
        routes = _mock_apis(router)
        async with Client(build_server(tool_deps())) as client:
            tools = LeadTools(client)
            for _ in range(2):
                deps = MvpDeps(llm=_llm(), search=tools, site=tools, crm=tools)  # type: ignore[arg-type]
                state = await build_graph(make_nodes(deps)).ainvoke(
                    {"run_id": run_id, "raw_input": MCP_LEAD}
                )
                assert state["crm"]["note_id"] == "444"
    assert routes["note"].call_count == 1
    assert routes["company"].call_count == 2  # upsert é idempotente por natureza


# --- regras do nó, com CRM falso ----------------------------------------------------------


@dataclass
class FakeCrm:
    fail: set[str] = field(default_factory=set)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def _maybe_fail(self, stage: str) -> None:
        if stage in self.fail:
            raise ToolRequestError(f"{stage} recusado: e-mail {EMAIL} inválido")

    async def upsert_company(self, company: CompanyProps) -> UpsertResult:
        self.calls.append(("company", company))
        self._maybe_fail("company")
        return UpsertResult(id="111", created=True)

    async def upsert_contact(self, contact: ContactProps) -> UpsertResult:
        self.calls.append(("contact", contact))
        self._maybe_fail("contact")
        return UpsertResult(id="333", created=True)

    async def associate(self, contact_id: str, company_id: str) -> None:
        self.calls.append(("associate", (contact_id, company_id)))

    async def create_note(
        self,
        body: str,
        *,
        run_id: str,
        company_ids: Sequence[str] = (),
        contact_ids: Sequence[str] = (),
    ) -> NoteCreated:
        self.calls.append(("note", (list(company_ids), list(contact_ids))))
        self._maybe_fail("note")
        return NoteCreated(id="444", created=True)


async def _run_fake(crm: FakeCrm, raw: dict[str, Any] | None = None) -> QualificationState:
    from tests.graph.test_mvp import SEARCH_OK, SITE_OK

    deps = MvpDeps(llm=_llm(), search=SEARCH_OK, site=SITE_OK, crm=crm)  # type: ignore[arg-type]
    state: QualificationState = await build_graph(make_nodes(deps)).ainvoke(
        {"run_id": str(uuid.uuid4()), "raw_input": raw or LEAD}
    )
    return state


async def test_falha_na_empresa_nao_derruba_e_mascara_o_email() -> None:
    crm = FakeCrm(fail={"company"})
    state = await _run_fake(crm)
    assert state["status"] == "completed"  # o resultado continua válido
    assert state["crm"] == {"contact_id": "333", "note_id": "444"}
    assert ("note", ([], ["333"])) in crm.calls  # Note só no contato
    assert not any(kind == "associate" for kind, _ in crm.calls)
    errors = " ".join(state["errors"])
    assert "crm empresa" in errors and EMAIL not in errors and "l***@example.com" in errors


async def test_lead_sem_dominio_grava_so_o_contato() -> None:
    crm = FakeCrm()
    state = await _run_fake(crm, LEAD | {"company_domain": None})
    assert [kind for kind, _ in crm.calls] == ["contact", "note"]
    assert state["crm"] == {"contact_id": "333", "note_id": "444"}


async def test_lead_sem_dominio_e_sem_email_nao_grava() -> None:
    crm = FakeCrm()
    state = await _run_fake(crm, LEAD | {"company_domain": None, "contact_email": None})
    assert crm.calls == []
    assert "nada a gravar" in " ".join(state["errors"])


async def test_lead_rejeitado_nao_chega_ao_crm() -> None:
    crm = FakeCrm()
    state = await _run_fake(crm, {"company_name": "x"})
    assert state["status"] == "rejected"
    assert crm.calls == []


async def test_falha_na_note_fica_registrada() -> None:
    state = await _run_fake(FakeCrm(fail={"note"}))
    assert "note_id" not in state["crm"]
    assert any(e.startswith("crm note") for e in state["errors"])


async def test_crm_recebe_so_campos_da_allowlist() -> None:
    crm = FakeCrm()
    state = await _run_fake(crm)
    company = next(v for k, v in crm.calls if k == "company")
    contact = next(v for k, v in crm.calls if k == "contact")
    assert company.ai_fit_score == state["result"].score
    assert contact.jobtitle == LEAD["contact_role"]
    assert contact.ai_run_id == state["run_id"]


async def test_crm_desligado_nao_grava() -> None:
    from tests.graph.test_mvp import SEARCH_OK, SITE_OK

    deps = MvpDeps(llm=_llm(), search=SEARCH_OK, site=SITE_OK)  # type: ignore[arg-type]
    state = await build_graph(make_nodes(deps)).ainvoke(
        {"run_id": str(uuid.uuid4()), "raw_input": LEAD}
    )
    assert "crm" not in state
    step = next(s for s in state["steps"] if s.node == "write_to_crm")
    assert step.route_reason == "CRM desativado"


async def test_note_tem_justificativa_por_criterio() -> None:
    state = await _run_fake(FakeCrm())
    text = note_text(state, state["result"])
    assert text.startswith("Qualificação por IA (FrotaSense): Tier A · score 100.0/100")
    for label in ("Setor", "Papel na compra", "Porte", "Intenção", "Região"):
        assert f"- {label}:" in text
    assert ASSESSMENT.rationale in text


async def test_guarda_do_no_sem_score_nao_grava() -> None:
    """Defesa em profundidade: mesmo chamado fora da rota, o nó não grava execução sem score."""
    crm = FakeCrm()
    node = make_write_to_crm(crm)
    update = await node({"run_id": "r", "raw_input": {}, "status": "failed"})  # type: ignore[misc]
    assert crm.calls == [] and "crm" not in update
