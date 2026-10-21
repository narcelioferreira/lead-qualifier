"""`search_company_web`: busca na web via Tavily, com cache.

A consulta é montada pelo agente (e, na T25, reformulada por ele), então é validada aqui:
tamanho limitado e sem caracteres de controle. Os resultados são texto **não confiável**:
saem sanitizados e truncados, e o prompt que os consome deve delimitá-los (T14).
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError
from tenacity.wait import wait_base

from app import retry
from app.schemas import sanitize_text
from tools_mcp.base import ToolCache, ToolRequestError, ToolUnavailableError, cache_key

TAVILY_URL = "https://api.tavily.com/search"
TOOL = "search_company_web"
MIN_QUERY_CHARS = 3
MAX_QUERY_CHARS = 400
MAX_SNIPPET_CHARS = 1000
MAX_TITLE_CHARS = 300
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# 432: limite da chave/plano; 433: limite do pay-as-you-go. Repetir não adianta.
_QUOTA_STATUSES = {432, 433}
_SPACES = re.compile(r"\s+")


class WebResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(max_length=MAX_TITLE_CHARS)
    url: HttpUrl
    snippet: str = Field(max_length=MAX_SNIPPET_CHARS)
    score: float | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    results: list[WebResult]
    retrieved_at: datetime
    cached: bool = False


def normalize_query(query: str) -> str:
    text = _SPACES.sub(" ", sanitize_text(query)).strip()
    if not MIN_QUERY_CHARS <= len(text) <= MAX_QUERY_CHARS:
        raise ToolRequestError(
            f"consulta deve ter entre {MIN_QUERY_CHARS} e {MAX_QUERY_CHARS} caracteres"
        )
    return text


class TavilySearch:
    def __init__(
        self,
        api_key: SecretStr,
        cache: ToolCache,
        *,
        max_results: int = 5,
        search_depth: Literal["basic", "advanced"] = "basic",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
        retry_sleep: retry.Sleep | None = None,
    ) -> None:
        if not 1 <= max_results <= 20:
            raise ValueError("max_results deve estar entre 1 e 20")
        self._api_key = api_key
        self._cache = cache
        self._max_results = max_results
        self._depth = search_depth
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._retry_sleep = retry_sleep

    def __repr__(self) -> str:
        return f"TavilySearch(max_results={self._max_results}, depth={self._depth!r})"

    async def search(self, query: str) -> SearchResult:
        text = normalize_query(query)
        params = {"query": text.lower(), "max_results": self._max_results, "depth": self._depth}
        key = cache_key(TOOL, params)
        hit = await self._cache.get(key)
        if hit is not None:
            return SearchResult.model_validate(hit | {"cached": True})

        body = {
            "query": text,
            "search_depth": self._depth,
            "max_results": self._max_results,
            "topic": "general",
            "country": "brazil",
            "include_answer": False,
            "include_raw_content": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
                response, _ = await retry.send_with_retry(
                    lambda: client.post(TAVILY_URL, json=body),
                    "tavily",
                    self._retry_wait,
                    self._retry_sleep,
                )
        except retry.UpstreamUnavailableError as exc:
            raise ToolUnavailableError(str(exc)) from exc
        except retry.UpstreamRequestError as exc:
            if exc.status in _QUOTA_STATUSES:
                raise ToolUnavailableError(
                    f"tavily: cota de créditos esgotada ({exc.status})"
                ) from exc
            raise ToolRequestError(str(exc)) from exc

        result = SearchResult(
            query=text,
            results=_parse_results(response.json().get("results") or []),
            retrieved_at=datetime.now(UTC),
        )
        await self._cache.set(key, TOOL, params, result.model_dump(mode="json", exclude={"cached"}))
        return result


def _parse_results(raw: list[Any]) -> list[WebResult]:
    results: list[WebResult] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            results.append(
                WebResult(
                    title=sanitize_text(str(item.get("title") or ""))[:MAX_TITLE_CHARS],
                    url=item.get("url"),
                    snippet=sanitize_text(str(item.get("content") or ""))[:MAX_SNIPPET_CHARS],
                    score=item.get("score"),
                )
            )
        except ValidationError:
            continue  # URL inválida ou fora de http(s): descarta o resultado
    return results
