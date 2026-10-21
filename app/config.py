"""Configuração da aplicação, carregada de variáveis de ambiente (e `.env` em desenvolvimento)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_API_KEY_LENGTH = 32


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
    ollama_base_url: HttpUrl = HttpUrl("http://localhost:11434")

    # Limites de entrada (defesa contra abuso de custo e prompt injection volumoso).
    max_message_chars: int = Field(default=4000, ge=100, le=20000)

    @field_validator("api_key")
    @classmethod
    def _api_key_strong(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < MIN_API_KEY_LENGTH:
            raise ValueError(f"API_KEY deve ter pelo menos {MIN_API_KEY_LENGTH} caracteres")
        if secret.startswith("troque-por"):
            raise ValueError("API_KEY ainda está com o valor de exemplo do .env.example")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
