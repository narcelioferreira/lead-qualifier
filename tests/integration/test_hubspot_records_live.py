"""Cliente de registros contra a conta de teste real. Rodar com `uv run pytest -m integration`.

Escreve na conta: uma empresa e um contato fictícios (domínios reservados), sempre os
mesmos, e uma Note por execução. Use só a conta de teste de desenvolvedor.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.config import Settings
from tools_mcp.hubspot import CompanyProps, ContactProps, HubSpotClient

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

DOMAIN = "frotasense-teste-t18.example"
# O HubSpot recusa e-mail em `.example`; `example.com` também é reservado (RFC 2606).
EMAIL = "compras.t18@example.com"


@pytest.fixture
def client() -> HubSpotClient:
    try:
        token = Settings().hubspot_token
    except ValidationError as exc:
        pytest.skip(f".env incompleto: {exc.error_count()} erro(s)")
    if token is None:
        pytest.skip("HUBSPOT_TOKEN não configurado")
    return HubSpotClient(token)


async def _qualify(client: HubSpotClient) -> tuple[str, str]:
    """Grava o mesmo lead como o `write_to_crm` fará na T20."""
    ai = {
        "ai_fit_tier": "B",
        "ai_fit_score": 68.5,
        "ai_confidence": 0.8,
        "ai_next_step": "Agendar demo com o gestor de frota.",
        "ai_run_id": str(uuid.uuid4()),
        "ai_prompt_version": "v2",
        "ai_qualified_at": datetime.now(UTC),
    }
    company = await client.upsert_company(
        CompanyProps(name="Transportes Teste T18 (fictícia)", domain=DOMAIN, **ai)
    )
    contact = await client.upsert_contact(
        ContactProps(email=EMAIL, jobtitle="Gerente de frota", **ai)
    )
    await client.associate(contact.id, company.id)
    await client.create_note(
        f"Qualificação de teste (T18), run {ai['ai_run_id']}.\nTier B, score 68,5.",
        company_ids=[company.id],
        contact_ids=[contact.id],
    )
    return company.id, contact.id


async def test_mesmo_lead_duas_vezes_nao_duplica(client: HubSpotClient) -> None:
    first = await _qualify(client)
    second = await _qualify(client)  # logo em seguida: a busca ainda pode não ter indexado
    assert first == second
