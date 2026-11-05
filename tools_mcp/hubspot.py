"""Cliente de registros do HubSpot: upsert de empresa e contato, associação e Note (T18).

Na T19 estes métodos viram as tools MCP `hubspot_*` do servidor `lead-tools`.

Idempotência: rodar o mesmo lead duas vezes não duplica registros.
- Contato: primeiro busca por `email`; sem resultado, faz upsert atômico por `email` (único).
- Empresa: primeiro busca por `domain` (acha empresas criadas à mão); sem resultado, faz upsert
  atômico por `ai_company_domain` (único, criado na T17). A busca do HubSpot leva alguns
  segundos para indexar registros novos; o upsert pela chave única fecha essa janela.
- Associação: `PUT` da associação padrão, idempotente por natureza.
- Note: cada qualificação gera uma Note; a idempotência por `run_id` fica no `write_to_crm` (T20).

**Registro existente só recebe `ai_*`:** nome e cargo vêm do lead, que é não confiável, e quem
informa um domínio ou e-mail não prova que é dono dele. Eles só entram na criação do registro.

Controles (OWASP ASI02): só propriedades da allowlist, com tipos e limites validados (o agente
não escreve `hubspot_owner_id`, `lifecyclestage` etc.); IDs só numéricos; nunca apaga; o corpo
da Note é texto não confiável (vem do LLM), então é escapado para HTML e truncado.
"""

import html
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
)
from tenacity.wait import wait_base

from app import retry
from app.schemas import CleanStr, Domain, Tier, sanitize_text
from tools_mcp.base import ToolRequestError
from tools_mcp.hubspot_http import DEFAULT_TIMEOUT, HubSpotHttp

# Limite do HubSpot para `hs_note_body` é 65.536; fica uma folga para as tags HTML.
MAX_NOTE_CHARS = 20_000
# Associações padrão (HUBSPOT_DEFINED) da API v3.
NOTE_TO_CONTACT = 202
NOTE_TO_COMPANY = 190

HubSpotId = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,20}$")]


# Id da execução do agente (UUID): chave de idempotência das escritas no CRM.
RunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]


class AiFields(BaseModel):
    """Propriedades `ai_*` gravadas pelo agente (criadas pelo setup da T17)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ai_fit_tier: Tier | None = None
    ai_fit_score: float | None = Field(default=None, ge=0, le=100)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    ai_next_step: Annotated[CleanStr, StringConstraints(max_length=1000)] | None = None
    ai_run_id: RunId | None = None
    ai_prompt_version: Annotated[str, StringConstraints(pattern=r"^v[0-9]{1,3}$")] | None = None
    ai_qualified_at: datetime | None = None

    def hubspot_properties(self) -> dict[str, str]:
        props: dict[str, str] = {}
        for name, value in self.model_dump(exclude_none=True).items():
            if isinstance(value, datetime):
                # Datetime do HubSpot: milissegundos desde a época, em UTC.
                aware = value if value.tzinfo else value.replace(tzinfo=UTC)
                props[name] = str(int(aware.timestamp() * 1000))
            else:
                props[name] = str(value)
        return props

    def ai_properties(self) -> dict[str, str]:
        """Só as `ai_*`: o que um registro já existente pode receber."""
        return {k: v for k, v in self.hubspot_properties().items() if k.startswith("ai_")}


class CompanyProps(AiFields):
    name: Annotated[CleanStr, StringConstraints(min_length=2, max_length=200)]
    domain: Domain


class ContactProps(AiFields):
    email: EmailStr
    jobtitle: Annotated[CleanStr, StringConstraints(max_length=120)] | None = None


class UpsertResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: HubSpotId
    created: bool


def note_html(text: str) -> str:
    """Texto não confiável → HTML seguro: escapado, truncado e com um `<p>` por parágrafo."""
    body = sanitize_text(text)[:MAX_NOTE_CHARS]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "".join(
        "<p>" + "<br>".join(html.escape(line) for line in p.splitlines()) + "</p>"
        for p in paragraphs
    )


class HubSpotClient:
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
        return "HubSpotClient()"

    async def upsert_company(self, props: CompanyProps) -> UpsertResult:
        async with self._http.client() as client:
            company_id = await self._find(client, "companies", "domain", props.domain)
            if company_id is not None:
                return await self._update_ai(client, "companies", company_id, props)
            return await self._batch_upsert(
                client,
                "companies",
                "ai_company_domain",
                props.domain,
                props.hubspot_properties() | {"ai_company_domain": props.domain},
            )

    async def upsert_contact(self, props: ContactProps) -> UpsertResult:
        # Minúsculas, como o HubSpot guarda: uma busca que falhasse pela caixa trocaria o cargo.
        email = str(props.email).lower()
        async with self._http.client() as client:
            contact_id = await self._find(client, "contacts", "email", email)
            if contact_id is not None:
                return await self._update_ai(client, "contacts", contact_id, props)
            properties = props.hubspot_properties() | {"email": email}
            return await self._batch_upsert(client, "contacts", "email", email, properties)

    async def associate(self, contact_id: str, company_id: str) -> None:
        contact, company = _valid_id(contact_id), _valid_id(company_id)
        async with self._http.client() as client:
            await self._http.send(
                client,
                "PUT",
                f"/crm/v4/objects/contacts/{contact}/associations/default/companies/{company}",
            )

    async def create_note(
        self,
        text: str,
        *,
        company_ids: Sequence[str] = (),
        contact_ids: Sequence[str] = (),
        timestamp: datetime | None = None,
    ) -> str:
        targets = [(NOTE_TO_COMPANY, _valid_id(i)) for i in company_ids] + [
            (NOTE_TO_CONTACT, _valid_id(i)) for i in contact_ids
        ]
        if not targets:
            raise ToolRequestError("a Note precisa de pelo menos uma empresa ou contato")
        body = note_html(text)
        if not body:
            raise ToolRequestError("a Note não pode ser vazia")
        when = timestamp or datetime.now(UTC)
        payload = {
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": when.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            },
            "associations": [
                {
                    "to": {"id": object_id},
                    "types": [
                        {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}
                    ],
                }
                for type_id, object_id in targets
            ],
        }
        async with self._http.client() as client:
            created = await self._http.send(client, "POST", "/crm/v3/objects/notes", payload)
        return _hubspot_id(created)

    async def _find(
        self, client: httpx.AsyncClient, object_type: str, prop: str, value: str
    ) -> str | None:
        """Id do registro mais antigo com `prop == value`, ou `None`."""
        found = await self._http.send(
            client,
            "POST",
            f"/crm/v3/objects/{object_type}/search",
            {
                "filterGroups": [
                    {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}
                ],
                "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
                "properties": [prop],
                "limit": 1,
            },
        )
        results = found.get("results") or []
        return _hubspot_id(results[0]) if results else None

    async def _update_ai(
        self,
        client: httpx.AsyncClient,
        object_type: str,
        object_id: str,
        props: AiFields,
    ) -> UpsertResult:
        ai_properties = props.ai_properties()
        if ai_properties:
            await self._http.send(
                client,
                "PATCH",
                f"/crm/v3/objects/{object_type}/{object_id}",
                {"properties": ai_properties},
            )
        return UpsertResult(id=object_id, created=False)

    async def _batch_upsert(
        self,
        client: httpx.AsyncClient,
        object_type: str,
        id_property: str,
        key: str,
        properties: dict[str, str],
    ) -> UpsertResult:
        body = await self._http.send(
            client,
            "POST",
            f"/crm/v3/objects/{object_type}/batch/upsert",
            {"inputs": [{"idProperty": id_property, "id": key, "properties": properties}]},
        )
        results = body.get("results") or []
        if len(results) != 1:
            raise ToolRequestError(f"hubspot: upsert de {object_type} sem resultado único")
        return UpsertResult(id=_hubspot_id(results[0]), created=bool(results[0].get("new")))


def _valid_id(value: str) -> str:
    try:
        return UpsertResult(id=value, created=False).id
    except ValidationError:
        raise ToolRequestError("hubspot: id inválido (só dígitos)") from None


def _hubspot_id(record: Any) -> str:
    if not isinstance(record, dict) or record.get("id") is None:
        raise ToolRequestError("hubspot: resposta sem id")
    return _valid_id(str(record["id"]))
