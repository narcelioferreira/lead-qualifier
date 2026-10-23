"""Setup das propriedades `ai_*` do HubSpot com HTTP mockado (respx). Nenhuma chamada real."""

import json
import re
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError
from tenacity import wait_none

from app.schemas import Tier
from tools_mcp.base import ToolRequestError, ToolUnavailableError
from tools_mcp.hubspot_schema import (
    GROUP_NAME,
    HUBSPOT_URL,
    OBJECT_TYPES,
    PROPERTIES,
    Action,
    HubSpotSchema,
    PropertySpec,
)

pytestmark = pytest.mark.anyio

FAKE_TOKEN = "pat-na1-teste-nao-e-um-token-real-0000"  # noqa: S105  # pragma: allowlist secret
_PATH = re.compile(r"^/crm/v3/properties/(?P<obj>[a-z]+)(?P<rest>/.*)?$")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeHubSpot:
    """HubSpot em memória: grupos e propriedades por objeto, com registro das escritas."""

    def __init__(self) -> None:
        self.groups: dict[str, list[dict[str, Any]]] = {obj: [] for obj in OBJECT_TYPES}
        self.props: dict[str, dict[str, dict[str, Any]]] = {
            obj: {"name": {"name": "name", "type": "string", "hubspotDefined": True}}
            for obj in OBJECT_TYPES
        }
        self.writes: list[tuple[str, str]] = []
        self.bodies: list[dict[str, Any]] = []
        self.auth: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auth.add(request.headers.get("authorization", ""))
        match = _PATH.match(request.url.path)
        assert match, request.url.path
        obj, rest = match["obj"], match["rest"] or ""
        body = json.loads(request.content) if request.content else None
        if request.method != "GET":
            self.writes.append((request.method, request.url.path))
            self.bodies.append(body)
        if rest == "/groups":
            if request.method == "GET":
                return httpx.Response(200, json={"results": self.groups[obj]})
            self.groups[obj].append(body)
            return httpx.Response(201, json=body)
        if rest == "" and request.method == "GET":
            return httpx.Response(200, json={"results": list(self.props[obj].values())})
        if rest == "" and request.method == "POST":
            if body["name"] in self.props[obj]:
                return httpx.Response(409, json={"category": "CONFLICT", "message": "existe"})
            self.props[obj][body["name"]] = body
            return httpx.Response(201, json=body)
        if request.method == "PATCH":
            name = rest.strip("/")
            self.props[obj][name] |= body
            return httpx.Response(200, json=self.props[obj][name])
        raise AssertionError(f"rota inesperada: {request.method} {request.url.path}")


def _schema() -> HubSpotSchema:
    return HubSpotSchema(SecretStr(FAKE_TOKEN), retry_wait=wait_none())


def _route(fake: FakeHubSpot) -> respx.Router:
    router = respx.mock(base_url=HUBSPOT_URL, assert_all_called=False)
    router.route().mock(side_effect=fake.handler)
    return router


def _actions(changes: list[Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for change in changes:
        totals[change.action] = totals.get(change.action, 0) + 1
    return totals


# --- definições --------------------------------------------------------------------------


def test_propriedades_da_arquitetura() -> None:
    assert {p.name for p in PROPERTIES} == {
        "ai_fit_tier",
        "ai_fit_score",
        "ai_confidence",
        "ai_next_step",
        "ai_run_id",
        "ai_prompt_version",
        "ai_qualified_at",
    }


def test_opcoes_do_tier_vem_do_enum() -> None:
    tier = next(p for p in PROPERTIES if p.name == "ai_fit_tier")
    assert [o.value for o in tier.options] == [t.value for t in Tier]


def test_spec_exige_prefixo_ai() -> None:
    with pytest.raises(ValidationError):
        PropertySpec(
            name="lifecyclestage", label="x", type="string", field_type="text", description=""
        )


def test_spec_opcoes_so_em_enumeration() -> None:
    with pytest.raises(ValidationError):
        PropertySpec(
            name="ai_x", label="x", type="enumeration", field_type="select", description=""
        )


def test_repr_sem_token() -> None:
    assert FAKE_TOKEN not in repr(_schema())


# --- idempotência ------------------------------------------------------------------------


async def test_primeira_execucao_cria_tudo_e_segunda_nao_muda_nada() -> None:
    fake = FakeHubSpot()
    with _route(fake):
        first = await _schema().sync()
        writes_first = len(fake.writes)
        second = await _schema().sync()

    per_object = len(PROPERTIES) + 1  # propriedades + grupo
    assert _actions(first) == {Action.CREATED: per_object * len(OBJECT_TYPES)}
    assert writes_first == per_object * len(OBJECT_TYPES)
    assert _actions(second) == {Action.UNCHANGED: per_object * len(OBJECT_TYPES)}
    assert len(fake.writes) == writes_first  # a segunda execução não escreve
    for obj in OBJECT_TYPES:
        assert [g["name"] for g in fake.groups[obj]] == [GROUP_NAME]
        assert {p["groupName"] for n, p in fake.props[obj].items() if n != "name"} == {GROUP_NAME}
    assert fake.auth == {f"Bearer {FAKE_TOKEN}"}


async def test_divergencia_vira_patch_so_dos_campos_editaveis() -> None:
    fake = FakeHubSpot()
    with _route(fake):
        await _schema().sync()
        fake.props["companies"]["ai_fit_tier"]["label"] = "editado à mão"
        fake.props["companies"]["ai_fit_tier"]["options"] = [{"label": "A", "value": "A"}]
        fake.writes.clear()
        changes = await _schema().sync()

    updated = [c for c in changes if c.action == Action.UPDATED]
    assert [(c.object_type, c.name, c.fields) for c in updated] == [
        ("companies", "ai_fit_tier", ("label", "options"))
    ]
    assert fake.writes == [("PATCH", "/crm/v3/properties/companies/ai_fit_tier")]
    assert not {"name", "type"} & fake.bodies[-1].keys()  # o PATCH não reenvia nome nem tipo
    assert fake.props["companies"]["ai_fit_tier"]["label"] == "AI · Tier de fit"


async def test_dry_run_nao_escreve() -> None:
    fake = FakeHubSpot()
    with _route(fake):
        changes = await _schema().sync(dry_run=True)
    assert all(c.action == Action.CREATED for c in changes)
    assert fake.writes == []


async def test_tipo_diferente_e_recusado_sem_escrever() -> None:
    fake = FakeHubSpot()
    fake.props["companies"]["ai_fit_score"] = {"name": "ai_fit_score", "type": "string"}
    with _route(fake), pytest.raises(ToolRequestError, match="tipo existente"):
        await _schema().sync(object_types=["companies"])
    assert ("PATCH", "/crm/v3/properties/companies/ai_fit_score") not in fake.writes


async def test_propriedade_nativa_com_prefixo_nao_e_alterada() -> None:
    fake = FakeHubSpot()
    fake.props["contacts"]["ai_run_id"] = {
        "name": "ai_run_id",
        "type": "string",
        "hubspotDefined": True,
    }
    with _route(fake), pytest.raises(ToolRequestError, match="nativa"):
        await _schema().sync(object_types=["contacts"])


async def test_nao_toca_propriedades_sem_prefixo() -> None:
    fake = FakeHubSpot()
    with _route(fake):
        await _schema().sync()
    for obj in OBJECT_TYPES:
        assert fake.props[obj]["name"] == {"name": "name", "type": "string", "hubspotDefined": True}
    assert all("/name" not in path for _, path in fake.writes)


# --- erros -------------------------------------------------------------------------------


@respx.mock(base_url=HUBSPOT_URL)
async def test_401_vira_erro_claro_sem_token(respx_mock: respx.Router) -> None:
    respx_mock.get("/crm/v3/properties/companies/groups").respond(
        401, json={"category": "INVALID_AUTHENTICATION", "message": "token inválido"}
    )
    with pytest.raises(ToolRequestError, match="token inválido ou expirado") as info:
        await _schema().sync(object_types=["companies"])
    assert FAKE_TOKEN not in str(info.value)


async def test_429_seguido_de_sucesso() -> None:
    fake = FakeHubSpot()
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={})
        return fake.handler(request)

    with respx.mock(base_url=HUBSPOT_URL) as router:
        router.route().mock(side_effect=flaky)
        changes = await _schema().sync(object_types=["companies"])
    assert len(changes) == len(PROPERTIES) + 1


@respx.mock(base_url=HUBSPOT_URL)
async def test_5xx_persistente_vira_indisponivel(respx_mock: respx.Router) -> None:
    respx_mock.get("/crm/v3/properties/companies/groups").respond(503)
    with pytest.raises(ToolUnavailableError):
        await _schema().sync(object_types=["companies"])


async def test_409_sugere_restaurar_arquivada() -> None:
    fake = FakeHubSpot()

    def archived(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/companies"):
            return httpx.Response(409, json={"category": "CONFLICT", "message": "arquivada"})
        return fake.handler(request)

    with respx.mock(base_url=HUBSPOT_URL) as router:
        router.route().mock(side_effect=archived)
        with pytest.raises(ToolRequestError, match="arquivada"):
            await _schema().sync(object_types=["companies"])


@respx.mock(base_url=HUBSPOT_URL)
async def test_400_preserva_categoria_do_hubspot(respx_mock: respx.Router) -> None:
    respx_mock.get("/crm/v3/properties/companies/groups").respond(
        400, json={"category": "VALIDATION_ERROR", "message": "campo inválido"}
    )
    with pytest.raises(ToolRequestError, match="VALIDATION_ERROR campo inválido"):
        await _schema().sync(object_types=["companies"])


@respx.mock(base_url=HUBSPOT_URL)
async def test_403_aponta_escopo_faltando(respx_mock: respx.Router) -> None:
    respx_mock.get("/crm/v3/properties/companies/groups").respond(
        403, json={"category": "MISSING_SCOPES", "message": "sem escopo"}
    )
    with pytest.raises(ToolRequestError, match="escopos"):
        await _schema().sync(object_types=["companies"])
