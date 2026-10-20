"""Conceitos da ontologia do ICP (ver docs/02-ontologia-icp.md)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SectorFit(StrEnum):
    TARGET = "target"
    ADJACENT = "adjacent"
    OUT = "out"
    UNKNOWN = "unknown"


class SizeBand(StrEnum):
    S_1_49 = "1-49"
    S_50_199 = "50-199"
    S_200_999 = "200-999"
    S_1000_PLUS = "1000+"
    UNKNOWN = "unknown"


class RegionFit(StrEnum):
    PRIORITY = "priority"
    SECONDARY = "secondary"
    ABROAD = "abroad"
    UNKNOWN = "unknown"


class CompanyKind(StrEnum):
    PROSPECT = "prospect"
    COMPETITOR = "competitor"
    VENDOR = "vendor"
    UNKNOWN = "unknown"


class Area(StrEnum):
    OPERATIONS = "operations"
    LOGISTICS = "logistics"
    FLEET = "fleet"
    FINANCE = "finance"
    EXECUTIVE = "executive"
    IT = "it"
    PROCUREMENT = "procurement"
    SALES = "sales"
    MARKETING = "marketing"
    HR = "hr"
    LEGAL = "legal"
    OTHER = "other"


class Seniority(StrEnum):
    C_LEVEL = "c_level"
    OWNER = "owner"
    DIRECTOR = "director"
    MANAGER = "manager"
    COORDINATOR = "coordinator"
    ANALYST = "analyst"
    INTERN = "intern"
    UNKNOWN = "unknown"


class BuyingRole(StrEnum):
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    USER = "user"
    NONE = "none"
    UNKNOWN = "unknown"


class IntentSignal(StrEnum):
    PAIN = "pain"
    PRICING_REQUEST = "pricing_request"
    VENDOR_SWITCH = "vendor_switch"
    CURIOSITY = "curiosity"
    NONE = "none"


class LeadFlag(StrEnum):
    STUDENT = "student"
    JOB_SEEKER = "job_seeker"
    INDIVIDUAL = "individual"
    SPAM = "spam"
    INJECTION = "injection"


class Certainty(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Criterion(StrEnum):
    SECTOR = "sector"
    BUYING_ROLE = "buying_role"
    SIZE = "size"
    INTENT = "intent"
    REGION = "region"


class LeadProfile(BaseModel):
    """Valores ontológicos de um lead, como extraídos pelo agente (ou pelo anotador humano).

    Este é o contrato entre o LLM ("extrai") e a rubrica ("pontua").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sector: SectorFit = SectorFit.UNKNOWN
    size: SizeBand = SizeBand.UNKNOWN
    region: RegionFit = RegionFit.UNKNOWN
    company_kind: CompanyKind = CompanyKind.UNKNOWN
    area: Area = Area.OTHER
    seniority: Seniority = Seniority.UNKNOWN
    intents: frozenset[IntentSignal] = Field(default_factory=frozenset)
    flags: frozenset[LeadFlag] = Field(default_factory=frozenset)
    certainty: dict[Criterion, Certainty] = Field(default_factory=dict)
