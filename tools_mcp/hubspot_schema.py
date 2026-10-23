"""Propriedades `ai_*` do HubSpot e sincronização idempotente (T17).

O agente grava nelas o resultado da qualificação (T18/T20). A sincronização lê o que já existe
e só cria o que falta ou corrige o que divergiu: rodar duas vezes não duplica nem quebra nada.

Controles (OWASP ASI02/ASI03):
- só toca propriedades e grupo com prefixo `ai_`, criados por este módulo; nunca apaga nada;
- mudança de `type` em propriedade existente é recusada (poderia corromper valores gravados);
- base URL fixa (sem SSRF) e token em `SecretStr`, fora de `repr`, logs e erros
  (`tools_mcp/hubspot_http.py`);
- `dry_run` mostra o plano sem nenhuma escrita.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from tenacity.wait import wait_base

from app import retry
from app.schemas import Tier
from tools_mcp.base import ToolRequestError
from tools_mcp.hubspot_http import DEFAULT_TIMEOUT, HubSpotHttp

PREFIX = "ai_"
GROUP_NAME = "ai_qualification"
GROUP_LABEL = "Qualificação por IA"
# Empresa: o fit ao ICP é da empresa. Contato: o vendedor trabalha a partir do contato.
OBJECT_TYPES: tuple[str, ...] = ("companies", "contacts")

PropertyType = Literal["enumeration", "number", "string", "datetime"]
FieldType = Literal["select", "number", "text", "textarea", "date"]


class PropertyOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    value: str
    display_order: int = Field(ge=0)


class PropertySpec(BaseModel):
    """Definição de uma propriedade `ai_*`, no formato da API de propriedades v3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^ai_[a-z0-9_]{1,60}$")
    label: str = Field(max_length=100)
    type: PropertyType
    field_type: FieldType
    description: str = Field(max_length=500)
    options: tuple[PropertyOption, ...] = ()
    # `hasUniqueValue` só pode ser definido na criação; serve de chave para upsert atômico.
    unique: bool = False
    object_types: tuple[str, ...] = OBJECT_TYPES

    @model_validator(mode="after")
    def _options_only_for_enumeration(self) -> "PropertySpec":
        if (self.type == "enumeration") != bool(self.options):
            raise ValueError("opções são obrigatórias em enumeration e proibidas nos demais tipos")
        return self

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "fieldType": self.field_type,
            "groupName": GROUP_NAME,
            "description": self.description,
            "formField": False,
            "hasUniqueValue": self.unique,
            "options": [
                {"label": o.label, "value": o.value, "displayOrder": o.display_order}
                for o in self.options
            ],
        }


PROPERTIES: tuple[PropertySpec, ...] = (
    PropertySpec(
        name="ai_fit_tier",
        label="AI · Tier de fit",
        type="enumeration",
        field_type="select",
        description="Tier de aderência ao ICP (A–D), calculado pelo código a partir da rubrica.",
        options=tuple(
            PropertyOption(label=tier.value, value=tier.value, display_order=i)
            for i, tier in enumerate(Tier)
        ),
    ),
    PropertySpec(
        name="ai_fit_score",
        label="AI · Score de fit",
        type="number",
        field_type="number",
        description="Score determinístico de 0 a 100 (rubric.yaml).",
    ),
    PropertySpec(
        name="ai_confidence",
        label="AI · Confiança",
        type="number",
        field_type="number",
        description="Confiança da qualificação, de 0 a 1.",
    ),
    PropertySpec(
        name="ai_next_step",
        label="AI · Próximo passo",
        type="string",
        field_type="textarea",
        description="Próximo passo comercial sugerido pelo agente.",
    ),
    PropertySpec(
        name="ai_run_id",
        label="AI · Run ID",
        type="string",
        field_type="text",
        description="ID da execução na auditoria (GET /v1/runs/{id}).",
    ),
    PropertySpec(
        name="ai_prompt_version",
        label="AI · Versão do prompt",
        type="string",
        field_type="text",
        description="Versão dos prompts usada na qualificação.",
    ),
    PropertySpec(
        name="ai_qualified_at",
        label="AI · Qualificado em",
        type="datetime",
        field_type="date",
        description="Data e hora da qualificação.",
    ),
    PropertySpec(
        name="ai_company_domain",
        label="AI · Domínio (chave)",
        type="string",
        field_type="text",
        description="Domínio normalizado, único: chave do upsert da empresa pelo agente (T18).",
        unique=True,
        object_types=("companies",),
    ),
)


class Action(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: str
    name: str
    action: Action
    fields: tuple[str, ...] = ()


def diff_fields(spec: PropertySpec, current: dict[str, Any]) -> tuple[str, ...]:
    """Campos editáveis que divergem. Levanta erro se o `type` mudou."""
    if current.get("type") != spec.type:
        raise ToolRequestError(
            f"{spec.name}: tipo existente {current.get('type')!r} difere de {spec.type!r}; "
            "corrija manualmente no HubSpot (o script não troca tipo para não corromper dados)"
        )
    if bool(current.get("hasUniqueValue")) != spec.unique:
        raise ToolRequestError(
            f"{spec.name}: hasUniqueValue existente difere de {spec.unique}; o HubSpot só "
            "permite defini-lo na criação (corrija manualmente)"
        )
    if current.get("hubspotDefined"):
        raise ToolRequestError(f"{spec.name}: propriedade nativa do HubSpot, não será alterada")
    wanted = spec.payload()
    changed = [
        key
        for key in ("label", "fieldType", "groupName", "description")
        if current.get(key) != wanted[key]
    ]
    have = {(o.get("value"), o.get("label")) for o in current.get("options") or []}
    want = {(o["value"], o["label"]) for o in wanted["options"]}
    if have != want:
        changed.append("options")
    return tuple(changed)


_ARCHIVED = "propriedade arquivada? restaure-a na interface do HubSpot e rode de novo"


class HubSpotSchema:
    """Cliente mínimo da API de propriedades v3 (só leitura, criação e atualização)."""

    def __init__(
        self,
        token: SecretStr,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
        retry_sleep: retry.Sleep | None = None,
    ) -> None:
        self._http = HubSpotHttp(
            token, timeout=timeout, retry_wait=retry_wait, retry_sleep=retry_sleep
        )

    def __repr__(self) -> str:
        return "HubSpotSchema()"

    async def sync(
        self,
        specs: Sequence[PropertySpec] = PROPERTIES,
        object_types: Sequence[str] = OBJECT_TYPES,
        *,
        dry_run: bool = False,
    ) -> list[Change]:
        changes: list[Change] = []
        async with self._http.client() as client:
            for object_type in object_types:
                changes.append(await self._sync_group(client, object_type, dry_run))
                current = await self._list_properties(client, object_type)
                for spec in specs:
                    if object_type not in spec.object_types:
                        continue
                    changes.append(
                        await self._sync_property(
                            client, object_type, spec, current.get(spec.name), dry_run
                        )
                    )
        return changes

    async def _sync_group(
        self, client: httpx.AsyncClient, object_type: str, dry_run: bool
    ) -> Change:
        path = f"/crm/v3/properties/{object_type}/groups"
        groups = (await self._http.send(client, "GET", path)).get("results") or []
        if any(g.get("name") == GROUP_NAME for g in groups):
            return Change(object_type=object_type, name=GROUP_NAME, action=Action.UNCHANGED)
        if not dry_run:
            await self._http.send(client, "POST", path, {"name": GROUP_NAME, "label": GROUP_LABEL})
        return Change(object_type=object_type, name=GROUP_NAME, action=Action.CREATED)

    async def _list_properties(
        self, client: httpx.AsyncClient, object_type: str
    ) -> dict[str, dict[str, Any]]:
        body = await self._http.send(client, "GET", f"/crm/v3/properties/{object_type}")
        return {
            p["name"]: p
            for p in body.get("results") or []
            if isinstance(p, dict) and str(p.get("name", "")).startswith(PREFIX)
        }

    async def _sync_property(
        self,
        client: httpx.AsyncClient,
        object_type: str,
        spec: PropertySpec,
        current: dict[str, Any] | None,
        dry_run: bool,
    ) -> Change:
        path = f"/crm/v3/properties/{object_type}"
        if current is None:
            if not dry_run:
                await self._http.send(client, "POST", path, spec.payload(), conflict_hint=_ARCHIVED)
            return Change(object_type=object_type, name=spec.name, action=Action.CREATED)
        fields = diff_fields(spec, current)
        if not fields:
            return Change(object_type=object_type, name=spec.name, action=Action.UNCHANGED)
        if not dry_run:
            # `name`, `type` e `hasUniqueValue` ficam de fora: o PATCH só envia campos editáveis.
            immutable = {"name", "type", "hasUniqueValue"}
            patch = {k: v for k, v in spec.payload().items() if k not in immutable}
            await self._http.send(client, "PATCH", f"{path}/{spec.name}", patch)
        return Change(object_type=object_type, name=spec.name, action=Action.UPDATED, fields=fields)
