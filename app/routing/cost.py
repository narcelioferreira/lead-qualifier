"""Catálogo de modelos (`models.yaml`) e conversão de uso de tokens em US$.

O custo é calculado em `Decimal` para não acumular erro de ponto flutuante ao somar milhares
de chamadas na avaliação. O YAML é lido com `yaml.safe_load` e validado por Pydantic.
"""

import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODELS_PATH = Path(__file__).parent / "models.yaml"
ONE_MILLION = Decimal(1_000_000)

# Nomes que apontam para versões móveis e quebram a reprodutibilidade da avaliação.
_FLOATING = re.compile(r"(latest|preview)", re.IGNORECASE)

_STRICT = ConfigDict(extra="forbid", frozen=True)


class CatalogError(ValueError):
    """Catálogo de modelos inválido."""


class Price(BaseModel):
    """Preço em US$ por 1M de tokens."""

    model_config = _STRICT

    input: Decimal = Field(ge=0)
    cached_input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _cache_not_pricier(self) -> Self:
        if self.cached_input > self.input:
            raise ValueError("cached_input não pode custar mais que input")
        return self


class ModelSpec(BaseModel):
    model_config = _STRICT

    key: str
    provider: Literal["groq", "ollama"]
    kind: Literal["chat", "embedding"]
    model: str = Field(min_length=1)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=128_000)
    # None = padrão do provedor (0,6 no gpt-oss, o que faz o mesmo lead variar de tier).
    temperature: float | None = Field(default=None, ge=0, le=2)
    # Só Ollama: liga/desliga o "thinking" de modelos que o suportam (None = não envia).
    think: bool | None = None
    price_per_1m: Price

    @model_validator(mode="after")
    def _pinned_version(self) -> Self:
        if _FLOATING.search(self.model):
            raise ValueError(f"{self.key}: versão móvel não é permitida ({self.model!r})")
        if self.provider == "ollama":
            if not self.model.partition(":")[2]:
                raise ValueError(f"{self.key}: fixe a tag do modelo Ollama (ex.: qwen3:4b)")
            if self.reasoning_effort is not None:
                raise ValueError(f"{self.key}: reasoning_effort não se aplica ao Ollama")
        elif self.think is not None:
            raise ValueError(f"{self.key}: think só se aplica ao Ollama")
        return self


class ModelCatalog(BaseModel):
    model_config = _STRICT

    version: int
    prices_checked_at: date
    models: dict[str, ModelSpec]

    @model_validator(mode="before")
    @classmethod
    def _inject_keys(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("models"), dict):
            models = data["models"]
            data = {**data, "models": {k: {**v, "key": k} for k, v in models.items()}}
        return data

    def get(self, key: str) -> ModelSpec:
        try:
            return self.models[key]
        except KeyError:
            raise CatalogError(f"modelo desconhecido: {key!r}") from None


class Usage(BaseModel):
    """Tokens de uma chamada. `cached_input_tokens` é um subconjunto de `input_tokens`."""

    model_config = _STRICT

    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    # Informativo: os tokens de raciocínio já estão contados em `output_tokens`.
    reasoning_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens maior que input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens maior que output_tokens")
        return self

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


def cost_usd(usage: Usage, spec: ModelSpec) -> Decimal:
    """Custo em US$: input não cacheado + input cacheado + output (inclui raciocínio)."""
    price = spec.price_per_1m
    uncached = usage.input_tokens - usage.cached_input_tokens
    total = (
        uncached * price.input
        + usage.cached_input_tokens * price.cached_input
        + usage.output_tokens * price.output
    )
    return total / ONE_MILLION


def load_catalog(path: Path = MODELS_PATH) -> ModelCatalog:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ModelCatalog.model_validate(data)
    except (yaml.YAMLError, ValueError) as exc:
        raise CatalogError(f"{path.name}: {exc}") from exc


@lru_cache
def get_catalog() -> ModelCatalog:
    return load_catalog()
