"""Política de roteamento (T29): tabela de casos, sem modelo nenhum."""

from types import SimpleNamespace

import pytest

from app.llm.base import LLMError, LLMOutputError, LLMRequestError, LLMUnavailableError
from app.ontology.models import (
    Area,
    Certainty,
    CompanyKind,
    Criterion,
    IntentSignal,
    LeadFlag,
    LeadProfile,
    RegionFit,
    SectorFit,
    Seniority,
    SizeBand,
)
from app.ontology.scoring import ScoreResult, compute_score
from app.routing.policy import (
    LARGE,
    MINI,
    ROUTING_PREFIX,
    SLM,
    Route,
    RoutingDecision,
    RoutingPolicy,
    Trigger,
    decisions_from_steps,
)

POLICY = RoutingPolicy()
HIGH = {c: Certainty.HIGH for c in (Criterion.SECTOR, Criterion.SIZE, Criterion.BUYING_ROLE)}


def profile(**changes: object) -> LeadProfile:
    base: dict[str, object] = {
        "sector": SectorFit.TARGET,
        "size": SizeBand.S_200_999,
        "region": RegionFit.PRIORITY,
        "company_kind": CompanyKind.PROSPECT,
        "area": Area.OPERATIONS,
        "seniority": Seniority.DIRECTOR,
        "intents": frozenset({IntentSignal.PRICING_REQUEST}),
        "certainty": HIGH,
    }
    return LeadProfile.model_validate(base | changes)


CLEAR_A = compute_score(profile())  # longe da fronteira
BORDERLINE_A = compute_score(
    profile(sector=SectorFit.ADJACENT, intents=frozenset({IntentSignal.CURIOSITY}))
)  # 76, a 1 ponto do limite do A


def test_fixtures_cover_the_cases() -> None:
    assert not CLEAR_A.is_borderline
    assert BORDERLINE_A.is_borderline, BORDERLINE_A.score


@pytest.mark.parametrize(
    ("stage", "current", "confidence", "score", "expected"),
    [
        # caso normal: confiança alta e longe da fronteira → fica no mini
        ("normalize", MINI, 0.9, CLEAR_A, None),
        # confiança baixa → modelo maior
        ("normalize", MINI, 0.4, CLEAR_A, (LARGE, Trigger.LOW_CONFIDENCE)),
        # exatamente no limite não escala (estritamente abaixo de 0,7)
        ("normalize", MINI, 0.7, CLEAR_A, None),
        # fronteira de tier → modelo maior
        ("normalize", MINI, 0.9, BORDERLINE_A, (LARGE, Trigger.BORDERLINE)),
        # confiança baixa tem precedência sobre a fronteira no motivo
        ("normalize", MINI, 0.4, BORDERLINE_A, (LARGE, Trigger.LOW_CONFIDENCE)),
        # já está no modelo maior: não escala de novo
        ("normalize", LARGE, 0.4, BORDERLINE_A, None),
        # etapa sem escalonamento
        ("assess", MINI, 0.4, BORDERLINE_A, None),
        ("guardrail", MINI, 0.4, BORDERLINE_A, None),
        ("etapa_desconhecida", MINI, 0.4, BORDERLINE_A, None),
    ],
)
def test_escalation_table(
    stage: str,
    current: str,
    confidence: float,
    score: ScoreResult,
    expected: tuple[str, Trigger] | None,
) -> None:
    decision = POLICY.escalation(stage, current, confidence, score)
    if expected is None:
        assert decision is None
    else:
        assert decision is not None
        assert (decision.model_key, decision.trigger) == expected
        assert decision.stage == stage


def test_tier_d_is_never_borderline_so_it_only_escalates_on_low_confidence() -> None:
    spam = compute_score(profile(flags=frozenset({LeadFlag.SPAM})))
    assert spam.tier.value == "D" and not spam.is_borderline
    assert POLICY.escalation("normalize", MINI, 0.9, spam) is None


UNAVAILABLE = LLMUnavailableError("groq: 503 depois de 3 tentativas")
INVALID = LLMOutputError("saída fora do schema")
REJECTED = LLMRequestError("groq: 400")


@pytest.mark.parametrize(
    ("stage", "failed", "error", "expected"),
    [
        # 5xx/429/timeout depois dos retries → modelo alternativo
        ("normalize", MINI, UNAVAILABLE, (LARGE, Trigger.UNAVAILABLE)),
        ("assess", MINI, UNAVAILABLE, (LARGE, Trigger.UNAVAILABLE)),
        ("agentic_research", MINI, UNAVAILABLE, (LARGE, Trigger.UNAVAILABLE)),
        ("suggest_next_step", MINI, UNAVAILABLE, (LARGE, Trigger.UNAVAILABLE)),
        # o último da rota não tem reserva
        ("normalize", LARGE, UNAVAILABLE, None),
        # saída inválida não troca de modelo, exceto no guardrail (ADR 0006)
        ("normalize", MINI, INVALID, None),
        ("guardrail", MINI, INVALID, (SLM, Trigger.INVALID_OUTPUT)),
        # guardrail: mini fora do ar cai no SLM; SLM fora do ar não tem para onde ir
        ("guardrail", MINI, UNAVAILABLE, (SLM, Trigger.UNAVAILABLE)),
        ("guardrail", SLM, UNAVAILABLE, None),
        # requisição rejeitada (4xx) é problema do pedido: não troca
        ("normalize", MINI, REJECTED, None),
        # modelo fora da rota e etapa sem rota própria
        ("normalize", "outro-modelo", UNAVAILABLE, None),
        ("etapa_desconhecida", MINI, UNAVAILABLE, None),
    ],
)
def test_fallback_table(
    stage: str, failed: str, error: LLMError, expected: tuple[str, Trigger] | None
) -> None:
    decision = POLICY.fallback(stage, failed, error)
    if expected is None:
        assert decision is None
    else:
        assert decision is not None
        assert (decision.model_key, decision.trigger) == expected


def test_slm_first_route_falls_back_to_the_mini() -> None:
    """O plano original (SLM primeiro): com o SLM fora do ar, o mini assume."""
    policy = RoutingPolicy(routes={"guardrail": Route((SLM, MINI))})
    assert policy.primary("guardrail") == SLM
    decision = policy.fallback("guardrail", SLM, LLMUnavailableError("ollama: conexão recusada"))
    assert decision is not None and decision.model_key == MINI


def test_primary_routes() -> None:
    assert POLICY.primary("guardrail") == MINI  # ADR 0006
    assert POLICY.primary("normalize") == MINI
    assert POLICY.primary("etapa_desconhecida") == MINI


def test_decision_reason_is_auditable_and_free_of_lead_text() -> None:
    decision = RoutingDecision("normalize", LARGE, Trigger.BORDERLINE, "score 72 na fronteira")
    assert decision.reason == f"{ROUTING_PREFIX} borderline → {LARGE} (score 72 na fronteira)"
    low = POLICY.escalation("normalize", MINI, 0.467, CLEAR_A)
    assert low is not None and "confiança 0.47 < 0.70" in low.reason


def test_decisions_from_steps_keeps_model_calls_and_policy_decisions_in_order() -> None:
    def step(node: str, model_key: str | None = None, reason: str | None = None) -> object:
        return SimpleNamespace(node=node, model_key=model_key, route_reason=reason)

    steps = [
        step("validate_input"),
        step("normalize", MINI),
        step("normalize", reason=f"{ROUTING_PREFIX} borderline → {LARGE} (x)"),
        step("normalize", LARGE),
        step("assess", reason="tentativa 1: fora do schema"),  # não é decisão de rota
        step("compute_score"),
    ]
    assert decisions_from_steps(steps) == [
        {"node": "normalize", "model_key": MINI, "route_reason": None},
        {"node": "normalize", "model_key": None, "route_reason": steps[2].route_reason},  # type: ignore[attr-defined]
        {"node": "normalize", "model_key": LARGE, "route_reason": None},
    ]
