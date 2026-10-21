"""Contratos de entrada e saída do agente (ver docs/03-contratos.md)."""

import ipaddress
import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
)

MAX_MESSAGE_CHARS = 4000

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Sufixos que nunca representam um site público de empresa (evita SSRF na pesquisa do site).
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".test")


def sanitize_text(value: str) -> str:
    """Remove caracteres de controle e invisíveis (exceto quebra de linha e tab).

    Caracteres de formatação invisíveis (categoria Cf, ex. zero-width) são usados para
    esconder instruções em ataques de prompt injection.
    """
    cleaned = "".join(
        ch for ch in value if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf"}
    )
    return unicodedata.normalize("NFKC", cleaned).strip()


def normalize_domain(value: str) -> str:
    """Normaliza 'https://www.Empresa.com.br/contato' para 'empresa.com.br' e valida.

    Rejeita IPs, localhost e sufixos internos: o domínio será usado para buscar o site
    da empresa, então não pode apontar para a rede interna (SSRF).
    """
    raw = value.strip().lower()
    if "://" not in raw:
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    if parts.username or parts.password or parts.port:
        raise ValueError("domínio não pode conter credenciais ou porta")
    host = (parts.hostname or "").rstrip(".")
    host = host.removeprefix("www.")
    if not host:
        raise ValueError("domínio vazio")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("informe um domínio, não um endereço IP")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError("domínio interno não é permitido")
    labels = host.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        raise ValueError("domínio inválido")
    if labels[-1].isdigit():
        raise ValueError("domínio inválido")
    if len(host) > 253:
        raise ValueError("domínio longo demais")
    return host


CleanStr = Annotated[str, AfterValidator(sanitize_text)]
Domain = Annotated[str, AfterValidator(normalize_domain)]


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class LeadSource(StrEnum):
    SITE_FORM = "site_form"
    DEMO_REQUEST = "demo_request"
    EVENT = "event"
    CONTENT = "content"
    API = "api"


class LeadInput(BaseModel):
    """Lead recebido pela API. Todo texto aqui é **não confiável** (pode conter injeção)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: Annotated[CleanStr, StringConstraints(min_length=2, max_length=200)]
    company_domain: Domain | None = None
    contact_role: Annotated[CleanStr, StringConstraints(min_length=2, max_length=120)]
    contact_email: EmailStr | None = None
    message: Annotated[CleanStr, StringConstraints(max_length=MAX_MESSAGE_CHARS)] = ""
    source: LeadSource = LeadSource.API

    @field_validator("company_domain", mode="before")
    @classmethod
    def _empty_domain_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class EvidenceSource(StrEnum):
    WEB_SEARCH = "web_search"
    COMPANY_SITE = "company_site"
    KNOWLEDGE_BASE = "knowledge_base"
    LEAD_MESSAGE = "lead_message"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: EvidenceSource
    source_url: HttpUrl | None = None
    snippet: Annotated[CleanStr, StringConstraints(max_length=1000)]
    retrieved_at: datetime


class CriterionScore(BaseModel):
    """Resultado de um critério da rubrica: valor ontológico → pontos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: str
    value: str
    points: float = Field(ge=0)
    max_points: float = Field(gt=0)
    evidence: list[Evidence] = Field(default_factory=list)


class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str = Field(max_length=300)
    owner: str = Field(max_length=60)
    sla_hours: int | None = Field(default=None, ge=1)
    talking_points: list[str] = Field(default_factory=list, max_length=5)
    kb_citations: list[str] = Field(default_factory=list)


class QualificationResult(BaseModel):
    """Saída final do agente, gravada no CRM e na auditoria."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    tier: Tier
    score: float = Field(ge=0, le=100)
    is_borderline: bool
    confidence: float = Field(ge=0, le=1)
    needs_human_review: bool
    disqualifiers: list[str] = Field(default_factory=list)
    caps_applied: list[str] = Field(default_factory=list)
    criteria: list[CriterionScore]
    next_step: NextStep | None = None
    rationale: str = Field(max_length=4000)
    prompt_version: str
    cost_usd: float = Field(ge=0)
