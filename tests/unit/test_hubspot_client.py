"""Cliente de registros do HubSpot com HTTP mockado (respx). Nenhuma chamada real."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError
from tenacity import wait_none

from tools_mcp.base import ToolRequestError, ToolUnavailableError
from tools_mcp.hubspot import (
    MAX_NOTE_CHARS,
    NOTE_TO_COMPANY,
    NOTE_TO_CONTACT,
    AiFields,
    CompanyProps,
    ContactProps,
    HubSpotClient,
    note_html,
)
from tools_mcp.hubspot_http import HUBSPOT_URL

pytestmark = pytest.mark.anyio

FAKE_TOKEN = "pat-na1-teste-nao-e-um-token-real-0000"  # noqa: S105  # pragma: allowlist secret
RUN_ID = "0b6f1a52-3c1e-4f0e-9a51-2f8d6f0c9e11"
SEARCH = "/crm/v3/objects/companies/search"
COMPANY_UPSERT = "/crm/v3/objects/companies/batch/upsert"
CONTACT_UPSERT = "/crm/v3/objects/contacts/batch/upsert"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _client() -> HubSpotClient:
    return HubSpotClient(SecretStr(FAKE_TOKEN), retry_wait=wait_none())


def _company(**kwargs: Any) -> CompanyProps:
    base: dict[str, Any] = {"name": "Transportes Modelo", "domain": "https://www.Modelo.com.br/"}
    return CompanyProps(**(base | kwargs))


def _json(route: respx.Route, call: int = -1) -> Any:
    return json.loads(route.calls[call].request.content)


# --- propriedades ------------------------------------------------------------------------


def test_ai_fields_formatam_para_o_hubspot() -> None:
    props = AiFields(
        ai_fit_tier="A",
        ai_fit_score=82.5,
        ai_confidence=0.9,
        ai_run_id=RUN_ID,
        ai_prompt_version="v2",
        ai_qualified_at=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
    ).hubspot_properties()
    assert props == {
        "ai_fit_tier": "A",
        "ai_fit_score": "82.5",
        "ai_confidence": "0.9",
        "ai_run_id": RUN_ID,
        "ai_prompt_version": "v2",
        "ai_qualified_at": "1792756800000",
    }


def test_datetime_sem_fuso_e_tratado_como_utc() -> None:
    naive = AiFields(ai_qualified_at=datetime(2026, 10, 23, 12, 0)).hubspot_properties()
    assert naive["ai_qualified_at"] == "1792756800000"


@pytest.mark.parametrize(
    "fields",
    [
        {"ai_fit_tier": "Z"},
        {"ai_fit_score": 101},
        {"ai_confidence": 1.5},
        {"ai_run_id": "não-é-uuid"},
        {"ai_prompt_version": "v2; drop"},
        {"hubspot_owner_id": "123"},  # fora da allowlist
        {"lifecyclestage": "customer"},
    ],
)
def test_allowlist_e_limites(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AiFields(**fields)


def test_dominio_normalizado_e_interno_bloqueado() -> None:
    assert _company().domain == "modelo.com.br"
    with pytest.raises(ValidationError):
        _company(domain="localhost")


def test_note_html_escapa_conteudo_nao_confiavel() -> None:
    body = note_html('Tier A\n<script>alert(1)</script>\n\n<a href="javascript:x">clique</a>')
    assert "<script>" not in body and "<a " not in body
    assert body == (
        "<p>Tier A<br>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
        "<p>&lt;a href=&quot;javascript:x&quot;&gt;clique&lt;/a&gt;</p>"
    )


def test_note_html_trunca_e_remove_invisiveis() -> None:
    assert "​" not in note_html("a​b")
    assert len(note_html("x" * (MAX_NOTE_CHARS + 500))) == MAX_NOTE_CHARS + len("<p></p>")


def test_repr_sem_token() -> None:
    assert FAKE_TOKEN not in repr(_client())


# --- empresa -----------------------------------------------------------------------------


@respx.mock(base_url=HUBSPOT_URL)
async def test_empresa_nova_usa_upsert_pela_chave_unica(respx_mock: respx.Router) -> None:
    search = respx_mock.post(SEARCH).respond(200, json={"total": 0, "results": []})
    upsert = respx_mock.post(COMPANY_UPSERT).respond(
        200, json={"status": "COMPLETE", "results": [{"id": "111", "new": True}]}
    )
    result = await _client().upsert_company(_company(ai_fit_tier="B", ai_run_id=RUN_ID))

    assert (result.id, result.created) == ("111", True)
    assert _json(search)["filterGroups"][0]["filters"][0] == {
        "propertyName": "domain",
        "operator": "EQ",
        "value": "modelo.com.br",
    }
    sent = _json(upsert)["inputs"][0]
    assert sent["idProperty"] == "ai_company_domain" and sent["id"] == "modelo.com.br"
    assert sent["properties"] == {
        "name": "Transportes Modelo",
        "domain": "modelo.com.br",
        "ai_company_domain": "modelo.com.br",
        "ai_fit_tier": "B",
        "ai_run_id": RUN_ID,
    }
    assert upsert.calls[0].request.headers["authorization"] == f"Bearer {FAKE_TOKEN}"


@respx.mock(base_url=HUBSPOT_URL, assert_all_called=False)
async def test_empresa_existente_e_atualizada_sem_duplicar(respx_mock: respx.Router) -> None:
    respx_mock.post(SEARCH).respond(200, json={"total": 1, "results": [{"id": "222"}]})
    patch = respx_mock.patch("/crm/v3/objects/companies/222").respond(200, json={"id": "222"})
    upsert = respx_mock.post(COMPANY_UPSERT)

    result = await _client().upsert_company(_company(ai_fit_score=70))

    assert (result.id, result.created) == ("222", False)
    assert not upsert.called
    # a chave única não é gravada no PATCH: a empresa pode ter sido criada à mão
    assert "ai_company_domain" not in _json(patch)["properties"]
    assert _json(patch)["properties"]["ai_fit_score"] == "70.0"


@respx.mock(base_url=HUBSPOT_URL)
async def test_busca_atrasada_cai_no_upsert_que_atualiza(respx_mock: respx.Router) -> None:
    """Busca ainda sem o registro recém-criado: o upsert pela chave acha e atualiza."""
    respx_mock.post(SEARCH).respond(200, json={"results": []})
    respx_mock.post(COMPANY_UPSERT).respond(200, json={"results": [{"id": "111", "new": False}]})
    result = await _client().upsert_company(_company())
    assert (result.id, result.created) == ("111", False)


@respx.mock(base_url=HUBSPOT_URL)
async def test_upsert_sem_resultado_unico_falha(respx_mock: respx.Router) -> None:
    respx_mock.post(SEARCH).respond(200, json={"results": []})
    respx_mock.post(COMPANY_UPSERT).respond(200, json={"results": []})
    with pytest.raises(ToolRequestError, match="resultado único"):
        await _client().upsert_company(_company())


@respx.mock(base_url=HUBSPOT_URL)
async def test_id_nao_numerico_na_resposta_e_rejeitado(respx_mock: respx.Router) -> None:
    respx_mock.post(SEARCH).respond(200, json={"results": [{"id": "../../owners"}]})
    with pytest.raises(ToolRequestError, match="id inválido"):
        await _client().upsert_company(_company())


# --- contato, associação e Note ----------------------------------------------------------


@respx.mock(base_url=HUBSPOT_URL)
async def test_contato_upsert_por_email(respx_mock: respx.Router) -> None:
    upsert = respx_mock.post(CONTACT_UPSERT).respond(
        200, json={"results": [{"id": "333", "new": True}]}
    )
    result = await _client().upsert_contact(
        ContactProps(email="Compras@Modelo.com.br", jobtitle="Gerente de frota", ai_fit_tier="A")
    )
    assert (result.id, result.created) == ("333", True)
    sent = _json(upsert)["inputs"][0]
    assert sent["idProperty"] == "email"
    assert sent["properties"]["jobtitle"] == "Gerente de frota"
    assert sent["properties"]["ai_fit_tier"] == "A"


@respx.mock(base_url=HUBSPOT_URL)
async def test_associacao_padrao(respx_mock: respx.Router) -> None:
    route = respx_mock.put(
        "/crm/v4/objects/contacts/333/associations/default/companies/111"
    ).respond(200, json={"status": "COMPLETE"})
    await _client().associate("333", "111")
    assert route.called


async def test_associacao_rejeita_id_invalido_sem_chamar_a_api() -> None:
    with respx.mock(base_url=HUBSPOT_URL) as router:
        with pytest.raises(ToolRequestError, match="id inválido"):
            await _client().associate("333/../../x", "111")
        assert not router.calls


@respx.mock(base_url=HUBSPOT_URL)
async def test_note_associada_a_empresa_e_contato(respx_mock: respx.Router) -> None:
    route = respx_mock.post("/crm/v3/objects/notes").respond(201, json={"id": "444"})
    note_id = await _client().create_note(
        "Tier A <b>",
        company_ids=["111"],
        contact_ids=["333"],
        timestamp=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
    )
    assert note_id == "444"
    sent = _json(route)
    assert sent["properties"] == {
        "hs_note_body": "<p>Tier A &lt;b&gt;</p>",
        "hs_timestamp": "2026-10-23T12:00:00Z",
    }
    assert [(a["to"]["id"], a["types"][0]["associationTypeId"]) for a in sent["associations"]] == [
        ("111", NOTE_TO_COMPANY),
        ("333", NOTE_TO_CONTACT),
    ]


@pytest.mark.parametrize(
    ("text", "kwargs", "match"),
    [
        ("ok", {}, "pelo menos uma"),
        ("   ", {"company_ids": ["111"]}, "vazia"),
    ],
)
async def test_note_invalida_nao_chama_a_api(text: str, kwargs: Any, match: str) -> None:
    with respx.mock(base_url=HUBSPOT_URL) as router:
        with pytest.raises(ToolRequestError, match=match):
            await _client().create_note(text, **kwargs)
        assert not router.calls


# --- erros -------------------------------------------------------------------------------


async def test_429_seguido_de_sucesso() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"retry-after": "0"}, json={}),
            httpx.Response(200, json={"results": [{"id": "333", "new": False}]}),
        ]
    )
    with respx.mock(base_url=HUBSPOT_URL) as router:
        route = router.post(CONTACT_UPSERT).mock(side_effect=lambda _: next(responses))
        result = await _client().upsert_contact(ContactProps(email="a@modelo.com.br"))
    assert result.id == "333" and route.call_count == 2


@respx.mock(base_url=HUBSPOT_URL)
async def test_401_sem_token_na_mensagem(respx_mock: respx.Router) -> None:
    respx_mock.post(CONTACT_UPSERT).respond(
        401, json={"category": "INVALID_AUTHENTICATION", "message": "token inválido"}
    )
    with pytest.raises(ToolRequestError, match="HTTP 401") as info:
        await _client().upsert_contact(ContactProps(email="a@modelo.com.br"))
    assert FAKE_TOKEN not in str(info.value)


@respx.mock(base_url=HUBSPOT_URL)
async def test_403_mostra_o_escopo_faltando(respx_mock: respx.Router) -> None:
    respx_mock.post("/crm/v3/objects/notes").respond(
        403, json={"category": "MISSING_SCOPES", "message": "requires crm.objects.contacts.write"}
    )
    with pytest.raises(ToolRequestError, match=r"crm\.objects\.contacts\.write"):
        await _client().create_note("ok", contact_ids=["333"])


@respx.mock(base_url=HUBSPOT_URL)
async def test_5xx_persistente_vira_indisponivel(respx_mock: respx.Router) -> None:
    respx_mock.post(SEARCH).respond(502)
    with pytest.raises(ToolUnavailableError):
        await _client().upsert_company(_company())
