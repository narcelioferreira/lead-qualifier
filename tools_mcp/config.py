"""Configuração do servidor MCP `lead-tools`, separada da configuração da API.

O container de tools recebe só o que usa (chaves da Tavily e do HubSpot, banco do cache e o
token do próprio servidor). A API nunca recebe essas chaves (ASI03).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_TOKEN_LENGTH = 32


class ToolsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # Token que os clientes MCP enviam como `Authorization: Bearer ...`. Obrigatório: as tools
    # escrevem no CRM, então o servidor não sobe sem autenticação (fail closed).
    tools_mcp_token: SecretStr
    tavily_api_key: SecretStr | None = None
    hubspot_token: SecretStr | None = None
    database_url: SecretStr

    tools_mcp_host: str = "127.0.0.1"
    tools_mcp_port: int = Field(default=8001, ge=1024, le=65535)
    # Valores aceitos no header `Host` (proteção contra DNS rebinding). Separados por vírgula.
    tools_mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*"
    # Domínios `.example` do dataset são servidos por fixtures (avaliação).
    fixtures_dir: Path | None = None

    @field_validator("tools_mcp_token")
    @classmethod
    def _token_strong(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_TOKEN_LENGTH:
            raise ValueError(f"TOOLS_MCP_TOKEN deve ter pelo menos {MIN_TOKEN_LENGTH} caracteres")
        return value

    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.tools_mcp_allowed_hosts.split(",") if h.strip()]


@lru_cache
def get_tools_settings() -> ToolsSettings:
    return ToolsSettings()
