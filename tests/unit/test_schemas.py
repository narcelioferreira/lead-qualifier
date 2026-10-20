from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    MAX_MESSAGE_CHARS,
    CriterionScore,
    Evidence,
    EvidenceSource,
    LeadInput,
    LeadSource,
    QualificationResult,
    Tier,
    normalize_domain,
)

VALID_LEAD = {
    "company_name": "Transportes Exemplo Ltda",
    "company_domain": "https://www.TransportesExemplo.com.br/contato",
    "contact_role": "Diretor de Operações",
    "contact_email": "lead-001@example.com",
    "message": "Quero uma proposta para 80 caminhões.",
    "source": "site_form",
}


def test_valid_lead_is_parsed_and_normalized() -> None:
    lead = LeadInput.model_validate(VALID_LEAD)
    assert lead.company_domain == "transportesexemplo.com.br"
    assert lead.source is LeadSource.SITE_FORM


def test_optional_fields_default() -> None:
    lead = LeadInput(company_name="ACME", contact_role="CEO")
    assert lead.company_domain is None
    assert lead.message == ""
    assert lead.source is LeadSource.API


def test_empty_domain_becomes_none() -> None:
    lead = LeadInput.model_validate({**VALID_LEAD, "company_domain": "   "})
    assert lead.company_domain is None


@pytest.mark.parametrize("field", ["company_name", "contact_role"])
def test_required_fields(field: str) -> None:
    data = {k: v for k, v in VALID_LEAD.items() if k != field}
    with pytest.raises(ValidationError):
        LeadInput.model_validate(data)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LeadInput.model_validate({**VALID_LEAD, "tier": "A"})


def test_message_too_long_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LeadInput.model_validate({**VALID_LEAD, "message": "x" * (MAX_MESSAGE_CHARS + 1)})


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LeadInput.model_validate({**VALID_LEAD, "contact_email": "nao-e-email"})


def test_control_and_invisible_chars_are_stripped() -> None:
    hidden = "Olá​‍\x00 equipe‮"
    lead = LeadInput.model_validate({**VALID_LEAD, "message": hidden})
    assert lead.message == "Olá equipe"


def test_lead_is_immutable() -> None:
    lead = LeadInput.model_validate(VALID_LEAD)
    with pytest.raises(ValidationError):
        lead.message = "outra"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("empresa.com.br", "empresa.com.br"),
        ("WWW.Empresa.COM.BR", "empresa.com.br"),
        ("https://www.empresa.com.br/sobre?x=1", "empresa.com.br"),
        ("http://sub.empresa.com/", "sub.empresa.com"),
        ("empresa.com.br.", "empresa.com.br"),
    ],
)
def test_normalize_domain_valid(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "localhost",
        "http://localhost:8000",
        "127.0.0.1",
        "http://169.254.169.254/latest/meta-data",  # metadata de cloud (SSRF clássico)
        "10.0.0.5",
        "[::1]",
        "intranet.local",
        "api.internal",
        "user:senha@empresa.com.br",
        "empresa.com.br:8080",
        "semponto",
        "-ruim-.com",
        "empresa .com",
        "1.2.3.4.5",
    ],
)
def test_normalize_domain_rejects_unsafe_or_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(raw)


def test_qualification_result_bounds() -> None:
    evidence = Evidence(
        source_type=EvidenceSource.COMPANY_SITE,
        source_url="https://empresa.com.br/sobre",
        snippet="Frota de 120 caminhões",
        retrieved_at=datetime.now(UTC),
    )
    base = {
        "run_id": "r1",
        "tier": "A",
        "score": 100,
        "is_borderline": False,
        "confidence": 0.9,
        "needs_human_review": False,
        "criteria": [
            CriterionScore(
                criterion="size", value="50-199", points=20, max_points=20, evidence=[evidence]
            )
        ],
        "rationale": "ok",
        "prompt_version": "v1",
        "cost_usd": 0.01,
    }
    result = QualificationResult.model_validate(base)
    assert result.tier is Tier.A
    for field, bad in [("score", 101), ("confidence", 1.5), ("cost_usd", -1)]:
        with pytest.raises(ValidationError):
            QualificationResult.model_validate({**base, field: bad})
