"""Testes da rubrica.

Os casos E1–E8 são os exemplos calculados à mão em docs/02-ontologia-icp.md.
"""

import pytest

from app.ontology.models import (
    Area,
    BuyingRole,
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
from app.ontology.scoring import compute_score
from app.schemas import Tier

I = IntentSignal  # noqa: E741

EXAMPLES = {
    "E1": (
        LeadProfile(
            sector=SectorFit.TARGET,
            size=SizeBand.S_50_199,
            region=RegionFit.PRIORITY,
            company_kind=CompanyKind.PROSPECT,
            area=Area.OPERATIONS,
            seniority=Seniority.DIRECTOR,
            intents=frozenset({I.PRICING_REQUEST}),
        ),
        100.0,
        Tier.A,
        False,
        (),
    ),
    "E2": (
        LeadProfile(
            sector=SectorFit.TARGET,
            size=SizeBand.S_200_999,
            region=RegionFit.PRIORITY,
            area=Area.FLEET,
            seniority=Seniority.COORDINATOR,
            intents=frozenset({I.CURIOSITY}),
        ),
        81.0,
        Tier.A,
        False,
        (),
    ),
    "E3": (
        LeadProfile(
            sector=SectorFit.ADJACENT,
            size=SizeBand.S_200_999,
            region=RegionFit.PRIORITY,
            area=Area.LOGISTICS,
            seniority=Seniority.MANAGER,
            intents=frozenset({I.PAIN}),
        ),
        85.0,
        Tier.A,
        False,
        (),
    ),
    "E4": (
        LeadProfile(
            sector=SectorFit.TARGET,
            size=SizeBand.S_1000_PLUS,
            region=RegionFit.PRIORITY,
            area=Area.FINANCE,
            seniority=Seniority.C_LEVEL,
            intents=frozenset({I.PRICING_REQUEST}),
        ),
        90.0,
        Tier.B,
        False,
        ("C1",),
    ),
    "E5": (
        LeadProfile(
            sector=SectorFit.TARGET,
            size=SizeBand.S_1_49,
            region=RegionFit.SECONDARY,
            area=Area.EXECUTIVE,
            seniority=Seniority.OWNER,
            intents=frozenset({I.CURIOSITY}),
        ),
        71.0,
        Tier.B,
        True,
        (),
    ),
    "E6": (
        LeadProfile(
            sector=SectorFit.TARGET,
            size=SizeBand.S_50_199,
            region=RegionFit.PRIORITY,
            area=Area.LOGISTICS,
            seniority=Seniority.INTERN,
            intents=frozenset({I.CURIOSITY}),
        ),
        66.0,
        Tier.C,
        False,
        ("C2", "C3"),
    ),
    "E7": (
        LeadProfile(
            sector=SectorFit.ADJACENT,
            size=SizeBand.S_200_999,
            region=RegionFit.PRIORITY,
            area=Area.PROCUREMENT,
            seniority=Seniority.ANALYST,
        ),
        52.5,
        Tier.C,
        True,
        ("C2",),
    ),
}


@pytest.mark.parametrize("example", sorted(EXAMPLES))
def test_hand_calculated_examples(example: str) -> None:
    profile, score, tier, borderline, caps = EXAMPLES[example]
    result = compute_score(profile)
    assert result.score == score
    assert result.tier is tier
    assert result.is_borderline is borderline
    assert result.caps_applied == caps
    assert result.disqualifiers == ()


def test_e8_competitor_is_disqualified_with_all_rules_recorded() -> None:
    profile = LeadProfile(
        sector=SectorFit.OUT,
        size=SizeBand.S_50_199,
        region=RegionFit.PRIORITY,
        company_kind=CompanyKind.COMPETITOR,
        area=Area.SALES,
        seniority=Seniority.MANAGER,
        intents=frozenset({I.CURIOSITY}),
    )
    result = compute_score(profile)
    assert result.tier is Tier.D
    assert result.disqualifiers == ("K2", "K6")
    assert result.disqualification_reason == "competitor"
    assert result.is_borderline is False
    assert result.needs_human_review is False


def test_breakdown_sums_to_score_and_respects_max() -> None:
    result = compute_score(EXAMPLES["E2"][0])
    assert round(sum(c.points for c in result.breakdown), 1) == result.score
    assert all(0 <= c.points <= c.max_points for c in result.breakdown)
    assert {c.criterion for c in result.breakdown} == {c.value for c in Criterion}
    assert result.buying_role is BuyingRole.INFLUENCER


def test_all_unknown_profile() -> None:
    result = compute_score(LeadProfile())
    # 30*.25 + 25*0 (role: other -> none) + 20*.3 + 0 + 10*.5 = 7.5 + 0 + 6 + 0 + 5
    assert result.score == 18.5
    assert result.tier is Tier.C
    assert result.needs_human_review is True  # setor e porte unknown


def test_unknown_seniority_in_ops_area_counts_as_uncertain() -> None:
    profile = LeadProfile(
        sector=SectorFit.TARGET,
        size=SizeBand.UNKNOWN,
        region=RegionFit.PRIORITY,
        area=Area.OPERATIONS,
        seniority=Seniority.UNKNOWN,
        intents=frozenset({I.PAIN}),
    )
    result = compute_score(profile)
    assert result.buying_role is BuyingRole.UNKNOWN
    assert result.needs_human_review is True


def test_low_certainty_triggers_review() -> None:
    profile = EXAMPLES["E1"][0].model_copy(
        update={"certainty": {Criterion.SECTOR: Certainty.LOW, Criterion.SIZE: Certainty.LOW}}
    )
    assert compute_score(profile).needs_human_review is True


def test_single_uncertain_criterion_does_not_trigger_review() -> None:
    profile = EXAMPLES["E1"][0].model_copy(update={"certainty": {Criterion.SIZE: Certainty.LOW}})
    assert compute_score(profile).needs_human_review is False


@pytest.mark.parametrize(
    ("change", "rule", "reason"),
    [
        ({"flags": frozenset({LeadFlag.INJECTION})}, "K1", "spam_or_manipulation"),
        ({"flags": frozenset({LeadFlag.SPAM})}, "K1", "spam_or_manipulation"),
        ({"company_kind": CompanyKind.VENDOR}, "K3", "vendor_pitch"),
        ({"flags": frozenset({LeadFlag.STUDENT})}, "K4", "not_a_buyer"),
        ({"flags": frozenset({LeadFlag.JOB_SEEKER})}, "K4", "not_a_buyer"),
        ({"flags": frozenset({LeadFlag.INDIVIDUAL})}, "K5", "individual_b2c"),
        ({"sector": SectorFit.OUT}, "K6", "out_of_sector"),
        ({"region": RegionFit.ABROAD}, "K7", "out_of_region"),
    ],
)
def test_each_disqualifier_turns_perfect_lead_into_d(
    change: dict[str, object], rule: str, reason: str
) -> None:
    profile = EXAMPLES["E1"][0].model_copy(update=change)
    result = compute_score(profile)
    assert result.tier is Tier.D
    assert result.disqualifiers[0] == rule
    assert result.disqualification_reason == reason


def test_injection_wins_precedence_over_other_rules() -> None:
    profile = EXAMPLES["E1"][0].model_copy(
        update={
            "flags": frozenset({LeadFlag.INJECTION, LeadFlag.STUDENT}),
            "company_kind": CompanyKind.COMPETITOR,
        }
    )
    result = compute_score(profile)
    assert result.disqualifiers == ("K1", "K2", "K4")
    assert result.disqualification_reason == "spam_or_manipulation"


def test_score_exactly_on_tier_a_limit_is_a() -> None:
    # target 30 + influencer 15 + 50-199 20 + sem intenção 0 + priority 10 = 75
    profile = LeadProfile(
        sector=SectorFit.TARGET,
        size=SizeBand.S_50_199,
        region=RegionFit.PRIORITY,
        area=Area.FLEET,
        seniority=Seniority.COORDINATOR,
    )
    result = compute_score(profile)
    assert result.score == 75.0
    assert result.tier is Tier.A
    assert result.is_borderline is True


def test_score_exactly_on_tier_b_limit_is_b() -> None:
    # adjacent 15 + influencer 15 + 200-999 20 + none 0 + 0,5*10 (unknown) = 55
    profile = LeadProfile(
        sector=SectorFit.ADJACENT,
        size=SizeBand.S_200_999,
        region=RegionFit.UNKNOWN,
        area=Area.IT,
        seniority=Seniority.MANAGER,
    )
    result = compute_score(profile)
    assert result.score == 55.0
    assert result.tier is Tier.B
    assert result.is_borderline is True


def test_strongest_intent_is_used() -> None:
    weak = EXAMPLES["E1"][0].model_copy(update={"intents": frozenset({I.CURIOSITY})})
    mixed = EXAMPLES["E1"][0].model_copy(update={"intents": frozenset({I.CURIOSITY, I.PAIN})})
    assert compute_score(weak).score == 91.0
    assert compute_score(mixed).score == 100.0


def test_determinism() -> None:
    profile = EXAMPLES["E5"][0]
    first = compute_score(profile)
    assert all(compute_score(profile) == first for _ in range(20))
