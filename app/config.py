"""Configuração da aplicação, carregada de variáveis de ambiente (e `.env` em desenvolvimento)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_API_KEY_LENGTH = 32
# Hosts em que o token do MCP pode ir em `http` puro: a própria máquina. Fora deles, só `https`.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: Literal["dev", "test", "prod"] = "dev"

    # Segredos: SecretStr evita que apareçam em logs, repr e tracebacks.
    api_key: SecretStr
    groq_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    hubspot_token: SecretStr | None = None
    langsmith_api_key: SecretStr | None = None

    database_url: SecretStr

    # Servidor MCP `lead-tools` (T19/T20): o grafo pesquisa e grava no CRM por ele, sem ter as
    # chaves da Tavily e do HubSpot.
    tools_mcp_url: HttpUrl = HttpUrl("http://127.0.0.1:8001/mcp")
    tools_mcp_token: SecretStr | None = None
    ollama_base_url: HttpUrl = HttpUrl("http://localhost:11434")

    # Limites de entrada (defesa contra abuso de custo e prompt injection volumoso).
    max_message_chars: int = Field(default=4000, ge=100, le=20000)

    # API (T21). Gravar no HubSpot é opt-in: dev e testes nunca escrevem no CRM sem querer.
    api_write_crm: bool = False
    api_prompt_version: str = Field(default="v2", pattern=r"^v[0-9]{1,3}$")
    # Plano gratuito da Groq (8K tokens/min, ~4,5K por lead): uma execução por vez, fila curta.
    api_max_concurrent_runs: int = Field(default=1, ge=1, le=4)
    api_max_pending_runs: int = Field(default=10, ge=1, le=100)
    api_max_body_bytes: int = Field(default=32_768, ge=1024, le=1_048_576)

    @field_validator("api_key")
    @classmethod
    def _api_key_strong(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < MIN_API_KEY_LENGTH:
            raise ValueError(f"API_KEY deve ter pelo menos {MIN_API_KEY_LENGTH} caracteres")
        if secret.startswith("troque-por"):
            raise ValueError("API_KEY ainda está com o valor de exemplo do .env.example")
        return value

    @field_validator("tools_mcp_url")
    @classmethod
    def _tools_mcp_url_safe(cls, value: HttpUrl) -> HttpUrl:
        # O Bearer token vai em toda requisição: em `http` só na própria máquina ou na rede
        # interna do compose (nome de serviço sem ponto, ex.: `tools-mcp`). Fora disso, `https`.
        host = value.host or ""
        internal = host in LOOPBACK_HOSTS or ("." not in host and ":" not in host)
        if value.scheme != "https" and not internal:
            raise ValueError("TOOLS_MCP_URL fora da máquina ou do compose exige https")
        if value.username or value.password:
            raise ValueError("TOOLS_MCP_URL não pode ter credenciais; use TOOLS_MCP_TOKEN")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
