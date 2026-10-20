"""Pontuação determinística do ICP: o LLM extrai os valores ontológicos, este módulo pontua.

Não há chamada de LLM nem aleatoriedade aqui: o mesmo `LeadProfile` sempre gera o mesmo
resultado, o que torna a regra de negócio auditável e testável.
"""

from pydantic import BaseModel, ConfigDict

from app.ontology.loader import (
    BuyingRoleTable,
    Rubric,
    default_buying_roles,
    default_rubric,
)
from app.ontology.models import (
    BuyingRole,
    Certainty,
    Criterion,
    IntentSignal,
    LeadProfile,
)
from app.schemas import CriterionScore, Tier

_TIER_ORDER = (Tier.A, Tier.B, Tier.C, Tier.D)  # do melhor para o pior
_UNKNOWN = "unknown"


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: float
    tier: Tier
    tier_by_score: Tier
    is_borderline: bool
    needs_human_review: bool
    buying_role: BuyingRole
    breakdown: tuple[CriterionScore, ...]
    disqualifiers: tuple[str, ...]  # IDs das regras K*, na ordem de precedência
    disqualification_reason: str | None
    caps_applied: tuple[str, ...]


def _worst(a: Tier, b: Tier) -> Tier:
    return max(a, b, key=_TIER_ORDER.index)


def _strongest_intent(intents: frozenset[IntentSignal], rubric: Rubric) -> IntentSignal:
    if not intents:
        return IntentSignal.NONE
    factors = rubric.criteria[Criterion.INTENT].factors
    # Desempate determinístico pelo nome, para não depender da ordem de iteração do set.
    return max(intents, key=lambda i: (factors[i.value], i.value))


def _tier_from_score(score: float, rubric: Rubric) -> Tier:
    if score >= rubric.tiers[Tier.A]:
        return Tier.A
    if score >= rubric.tiers[Tier.B]:
        return Tier.B
    return Tier.C


def compute_score(
    profile: LeadProfile,
    rubric: Rubric | None = None,
    roles: BuyingRoleTable | None = None,
) -> ScoreResult:
    rubric = rubric or default_rubric()
    roles = roles or default_buying_roles()

    buying_role = roles.derive(profile.seniority, profile.area)
    values = {
        Criterion.SECTOR: profile.sector,
        Criterion.BUYING_ROLE: buying_role,
        Criterion.SIZE: profile.size,
        Criterion.INTENT: _strongest_intent(profile.intents, rubric),
        Criterion.REGION: profile.region,
    }

    breakdown = tuple(
        CriterionScore(
            criterion=criterion.value,
            value=value.value,
            points=round(rubric.points(criterion, value), 2),
            max_points=rubric.criteria[criterion].weight,
        )
        for criterion, value in values.items()
    )
    score = round(sum(item.points for item in breakdown), 1)
    tier_by_score = _tier_from_score(score, rubric)

    disqualifiers = tuple(
        rule.id
        for rule in rubric.disqualifiers
        if (rule.flags & profile.flags)
        or profile.company_kind in rule.company_kind
        or profile.sector in rule.sector
        or profile.region in rule.region
    )
    reason = next((r.reason for r in rubric.disqualifiers if r.id in disqualifiers), None)

    caps_applied: list[str] = []
    tier = tier_by_score
    for cap in rubric.caps:
        hit = (
            profile.size in cap.size
            or buying_role in cap.buying_role
            or (bool(cap.buying_role_not_in) and buying_role not in cap.buying_role_not_in)
        )
        if hit:
            caps_applied.append(cap.id)
            tier = _worst(tier, cap.max_tier)

    if disqualifiers:
        tier = Tier.D

    is_borderline = tier is not Tier.D and any(
        abs(score - limit) <= rubric.borderline_margin for limit in rubric.tiers.values()
    )

    uncertain = sum(
        1
        for criterion in rubric.review.critical_criteria
        if values[criterion].value == _UNKNOWN or profile.certainty.get(criterion) is Certainty.LOW
    )
    needs_review = tier is not Tier.D and uncertain >= rubric.review.min_uncertain_to_review

    return ScoreResult(
        score=score,
        tier=tier,
        tier_by_score=tier_by_score,
        is_borderline=is_borderline,
        needs_human_review=needs_review,
        buying_role=buying_role,
        breakdown=breakdown,
        disqualifiers=disqualifiers,
        disqualification_reason=reason,
        caps_applied=tuple(caps_applied),
    )
