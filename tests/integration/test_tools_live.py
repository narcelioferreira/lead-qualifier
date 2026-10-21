"""Ferramentas de pesquisa contra serviços reais. Rodar com `uv run pytest -m integration`.

Gasta 3 créditos da Tavily por execução (busca `basic`). Os sites são os oficiais de 3
empresas do dataset, conferidos na T08.
"""

import pytest
from pydantic import SecretStr, ValidationError

from app.audit.db import create_engine, session_factory
from app.config import Settings
from tools_mcp.base import MemoryCache, PostgresCache, cache_key
from tools_mcp.search import TavilySearch
from tools_mcp.site import SiteFetcher

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

COMPANIES = [
    ("Gobor Transportes", "gobor.com.br"),
    ("Atual Cargas transportadora", "atualcargas.com.br"),
    ("Transportes Della Volpe", "dellavolpe.com.br"),
]


@pytest.fixture
def settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        pytest.skip(f".env incompleto: {exc.error_count()} erro(s)")


async def test_postgres_cache_roundtrip_and_upsert(migrated: str) -> None:
    engine = create_engine(SecretStr(migrated))
    cache = PostgresCache(session_factory(engine))
    key = cache_key("teste", {"q": "gobor"})
    assert await cache.get(key) is None
    await cache.set(key, "teste", {"q": "gobor"}, {"v": 1})
    await cache.set(key, "teste", {"q": "gobor"}, {"v": 2})  # sobrescreve, sem duplicar
    assert await cache.get(key) == {"v": 2}
    await engine.dispose()


@pytest.mark.parametrize(("query", "domain"), COMPANIES)
async def test_tavily_live(settings: Settings, query: str, domain: str) -> None:
    if settings.tavily_api_key is None:
        pytest.skip("TAVILY_API_KEY ausente")
    result = await TavilySearch(settings.tavily_api_key, MemoryCache()).search(query)
    assert result.results
    # A ordem do buscador varia, e o site oficial nem sempre aparece (perfis e guias, sim):
    # exige-se só relevância, ou seja, algum resultado que cite a empresa.
    name = domain.split(".")[0]
    assert any(
        name in f"{r.url} {r.title} {r.snippet}".lower().replace(" ", "") for r in result.results
    ), [str(r.url) for r in result.results]


@pytest.mark.parametrize(("_query", "domain"), COMPANIES)
async def test_site_live(_query: str, domain: str) -> None:
    content = await SiteFetcher(MemoryCache()).fetch(domain)
    assert content.pages, content.errors
    assert content.pages[0].kind == "home"
    assert len(content.pages[0].text) > 100
