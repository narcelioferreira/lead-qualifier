"""Chamada real mínima a cada provedor. Rodar com `uv run pytest -m integration`.

Exige `OPENAI_API_KEY` no `.env` e o Ollama rodando com o modelo do catálogo. Custo esperado
da chamada à OpenAI: bem abaixo de US$ 0,001.
"""

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.llm.base import Message
from app.llm.ollama_client import OllamaClient
from app.llm.openai_client import OpenAIClient
from app.ontology.models import SectorFit
from app.routing.cost import get_catalog

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

MESSAGES = [
    Message(
        role="system", content="Classifique o setor da empresa descrita entre <lead> e </lead>."
    ),
    Message(
        role="user", content="<lead>Transportadora rodoviária de cargas com 80 caminhões.</lead>"
    ),
]


class SectorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector: SectorFit


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        pytest.skip(f".env incompleto: {exc.error_count()} erro(s)")


async def test_openai_live(settings: Settings) -> None:
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY ausente")
    spec = get_catalog().get("openai-mini")
    result = await OpenAIClient(settings.openai_api_key).structured(spec, MESSAGES, SectorAnswer)
    assert result.parsed.sector is SectorFit.TARGET
    assert result.usage.input_tokens > 0
    assert 0 < result.cost_usd < 0.001
    assert result.model.startswith("gpt-5.4-mini")


async def test_ollama_live(settings: Settings) -> None:
    base = str(settings.ollama_base_url).rstrip("/")
    try:
        httpx.get(f"{base}/api/tags", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Ollama não está rodando")
    spec = get_catalog().get("ollama-slm")
    result = await OllamaClient(settings.ollama_base_url).structured(spec, MESSAGES, SectorAnswer)
    assert isinstance(result.parsed.sector, SectorFit)
    assert result.cost_usd == 0
