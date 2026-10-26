"""Nó `write_to_crm` (T20): grava o resultado no HubSpot pelo servidor MCP `lead-tools`.

Ordem: empresa (pelo domínio) → contato (pelo e-mail) → associação → Note com a justificativa
por critério. **Idempotente por `run_id`:** os upserts usam chaves únicas do HubSpot e a Note é
registrada pelo `run_id` no servidor, então repetir o nó (retry, retomada) não duplica nada.

Falha no CRM não derruba a execução (ASI08): o resultado continua válido, o erro vai para a
auditoria e as etapas seguintes que dependem do id que faltou são puladas. O e-mail do lead é
mascarado nos erros gravados (LGPD).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from app.audit.repository import StepRecord, mask_email
from app.graph.builder import Node
from app.graph.nodes.core import build_result
from app.graph.state import QualificationState
from app.ontology.models import Criterion
from app.schemas import NextStep, QualificationResult
from tools_mcp.base import ToolError
from tools_mcp.hubspot import AiFields, CompanyProps, ContactProps, UpsertResult

CRITERION_LABELS = {
    Criterion.SECTOR.value: "Setor",
    Criterion.BUYING_ROLE.value: "Papel na compra",
    Criterion.SIZE.value: "Porte",
    Criterion.INTENT.value: "Intenção",
    Criterion.REGION.value: "Região",
}


class NoteRef(Protocol):
    id: str
    created: bool


class CrmWriter(Protocol):
    async def upsert_company(self, company: CompanyProps) -> UpsertResult: ...

    async def upsert_contact(self, contact: ContactProps) -> UpsertResult: ...

    async def associate(self, contact_id: str, company_id: str) -> None: ...

    async def create_note(
        self,
        body: str,
        *,
        run_id: str,
        company_ids: Sequence[str] = (),
        contact_ids: Sequence[str] = (),
    ) -> NoteRef: ...


def should_write(state: QualificationState) -> bool:
    """Só execuções com score vão ao CRM: rejeitado ou falho não tem tier para gravar."""
    return state.get("status") not in {"rejected", "failed"} and "score" in state


def next_step_text(step: NextStep) -> str:
    """Resumo de uma linha para a propriedade `ai_next_step` (até 1.000 caracteres)."""
    sla = f"em até {step.sla_hours} h úteis" if step.sla_hours else "sem prazo comercial"
    return f"{step.action} Responsável: {step.owner}, {sla}."[:1000]


def note_text(state: QualificationState, result: QualificationResult) -> str:
    """Justificativa por critério, em texto puro (o cliente HubSpot escapa o HTML)."""
    header = [
        f"Qualificação por IA (FrotaSense): Tier {result.tier.value} · score "
        f"{result.score:.1f}/100 · confiança {result.confidence:.0%}"
    ]
    if result.disqualifiers:
        reason = state["score"].disqualification_reason or ""
        header.append(f"Regras eliminatórias: {', '.join(result.disqualifiers)}. {reason}".strip())
    if result.caps_applied:
        header.append(f"Tetos aplicados: {', '.join(result.caps_applied)}")
    if result.needs_human_review or result.is_borderline:
        header.append("Revisão humana recomendada (fronteira entre tiers ou baixa certeza).")
    criteria = ["Critérios:"] + [
        f"- {CRITERION_LABELS.get(c.criterion, c.criterion)}: {c.value} "
        f"({c.points:g}/{c.max_points:g})"
        for c in result.criteria
    ]
    sections = [
        "\n".join(header),
        "\n".join(criteria),
        f"Justificativa: {result.rationale or '(indisponível)'}",
    ]
    if result.next_step is not None:
        step = result.next_step
        lines = [f"Próximo passo: {next_step_text(step)}"]
        lines += [f"- {point}" for point in step.talking_points]
        if step.kb_citations:
            lines.append(f"Fontes (base de conhecimento): {', '.join(step.kb_citations)}")
        sections.append("\n".join(lines))
    sections.append(f"run_id {result.run_id} · prompt {result.prompt_version}")
    return "\n\n".join(sections)


def _ai_fields(result: QualificationResult, qualified_at: datetime) -> dict[str, Any]:
    fields = AiFields(
        ai_fit_tier=result.tier,
        ai_fit_score=result.score,
        ai_confidence=result.confidence,
        ai_next_step=next_step_text(result.next_step) if result.next_step else None,
        ai_run_id=result.run_id,
        ai_prompt_version=result.prompt_version,
        ai_qualified_at=qualified_at,
    )
    return fields.model_dump(exclude_none=True)


def make_write_to_crm(crm: CrmWriter) -> Node:
    async def write_to_crm(state: QualificationState) -> dict[str, Any]:
        if not should_write(state):
            return {"steps": [StepRecord(node="write_to_crm", route_reason="sem score: não grava")]}
        lead = state["lead"]
        result = build_result(state)
        ids: dict[str, str] = {}
        errors: list[str] = []
        try:
            fields = _ai_fields(result, datetime.now(UTC))
        except ValidationError as exc:  # ex.: versão de prompt fora do padrão das propriedades
            errors.append(f"crm: propriedades ai_* inválidas ({exc.error_count()} erro(s))")
            return {
                "errors": errors,
                "steps": [StepRecord(node="write_to_crm", output={"errors": 1})],
            }

        def failed(stage: str, exc: Exception) -> None:
            message = str(exc)
            if lead.contact_email:  # a mensagem do HubSpot pode ecoar o e-mail
                message = message.replace(lead.contact_email, mask_email(lead.contact_email) or "")
            errors.append(f"crm {stage}: {message}"[:300])

        if lead.company_domain:
            try:
                company = CompanyProps(name=lead.company_name, domain=lead.company_domain, **fields)
                ids["company_id"] = (await crm.upsert_company(company)).id
            except (ToolError, ValidationError) as exc:
                failed("empresa", exc)
        if lead.contact_email:
            try:
                contact = ContactProps(
                    email=lead.contact_email, jobtitle=lead.contact_role, **fields
                )
                ids["contact_id"] = (await crm.upsert_contact(contact)).id
            except (ToolError, ValidationError) as exc:
                failed("contato", exc)
        if {"company_id", "contact_id"} <= ids.keys():
            try:
                await crm.associate(ids["contact_id"], ids["company_id"])
            except ToolError as exc:
                failed("associação", exc)
        note_created = None
        if ids:
            try:
                note = await crm.create_note(
                    note_text(state, result),
                    run_id=state["run_id"],
                    company_ids=[ids["company_id"]] if "company_id" in ids else [],
                    contact_ids=[ids["contact_id"]] if "contact_id" in ids else [],
                )
                ids["note_id"], note_created = note.id, note.created
            except ToolError as exc:
                failed("note", exc)
        elif not errors:
            errors.append("crm: lead sem domínio e sem e-mail, nada a gravar")
        return {
            "crm": ids,
            "errors": errors,
            "steps": [
                StepRecord(
                    node="write_to_crm",
                    output={**ids, "note_created": note_created, "errors": len(errors)},
                )
            ],
        }

    return write_to_crm
