"""Setup do HubSpot contra a conta de teste real. Rodar com `uv run pytest -m integration`.

Escreve na conta (cria o grupo e as propriedades `ai_*` na primeira vez). Use só a conta de
teste de desenvolvedor, nunca um portal de produção.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from tools_mcp.hubspot_schema import Action, HubSpotSchema

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def schema() -> HubSpotSchema:
    try:
        token = Settings().hubspot_token
    except ValidationError as exc:
        pytest.skip(f".env incompleto: {exc.error_count()} erro(s)")
    if token is None:
        pytest.skip("HUBSPOT_TOKEN não configurado")
    return HubSpotSchema(token)


async def test_setup_idempotente_na_conta_real(schema: HubSpotSchema) -> None:
    await schema.sync()
    second = await schema.sync()
    assert {change.action for change in second} == {Action.UNCHANGED}
