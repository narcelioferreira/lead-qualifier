"""Erros e cache comuns às ferramentas de pesquisa.

Na T19 estas funções viram tools MCP do servidor `lead-tools`. Até lá são chamadas direto.
"""

import hashlib
import json
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import ToolCacheEntry


class ToolError(Exception):
    """Erro de uma ferramenta. A mensagem nunca contém segredos nem conteúdo do site."""


class ToolUnavailableError(ToolError):
    """Serviço indisponível (rede, timeout, 5xx, 429 persistente ou cota esgotada)."""


class ToolRequestError(ToolError):
    """Requisição inválida (parâmetro fora do limite, chave inválida, domínio bloqueado)."""


def cache_key(tool: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"tool": tool, **params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ToolCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(
        self, key: str, tool: str, request: dict[str, Any], response: dict[str, Any]
    ) -> None: ...


class MemoryCache:
    """Cache em memória (testes e uso local sem banco)."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    async def set(
        self, key: str, tool: str, request: dict[str, Any], response: dict[str, Any]
    ) -> None:
        self.entries[key] = response


class PostgresCache:
    """Cache na tabela `tool_cache` (migration 0002)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            response: dict[str, Any] | None = await session.scalar(
                select(ToolCacheEntry.response).where(ToolCacheEntry.key == key)
            )
            return response

    async def set(
        self, key: str, tool: str, request: dict[str, Any], response: dict[str, Any]
    ) -> None:
        stmt = insert(ToolCacheEntry).values(key=key, tool=tool, request=request, response=response)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ToolCacheEntry.key],
            set_={"response": stmt.excluded.response, "created_at": stmt.excluded.created_at},
        )
        async with self._sessions.begin() as session:
            await session.execute(stmt)
