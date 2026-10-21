"""Saídas estruturadas do LLM e o mapeamento determinístico para a ontologia.

O LLM extrai **fatos** (CNAE, UF, país, funcionários, frota) e classifica conceitos com
valores enumerados. O código converte os fatos em `SectorFit`, `RegionFit` e `SizeBand` pelas
taxonomias de `app/ontology/` e calcula a confiança. Nada de nota vem do LLM.
"""

import re
from collections.abc import Sequence
from enum import StrEnum
from functools import cache

from pydantic import BaseModel, ConfigDict, Field

from app.ontology.loader import (
    BRAZIL_UFS,
    RegionTaxonomy,
    SectorTaxonomy,
    load_region_taxonomy,
    load_sector_taxonomy,
)
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

UF = StrEnum("UF", {uf: uf for uf in sorted(BRAZIL_UFS)})  # type: ignore[misc]
# docs/02-ontologia-icp.md: com só a frota, ~2,5 funcionários por veículo e certeza baixa.
EMPLOYEES_PER_VEHICLE = 2.5
CNAE_MIN_DIGITS = 4  # divisão (2) + grupo (1) + classe (1): abaixo disso não classifica
_CERTAINTY_WEIGHT = {Certainty.HIGH: 1.0, Certainty.MEDIUM: 0.7, Certainty.LOW: 0.4}
_UNKNOWN_WEIGHT = 0.2

_STRICT = ConfigDict(extra="forbid", frozen=True)


class Extraction(BaseModel):
    """Saída do `normalize_to_ontology`."""

    model_config = _STRICT

    cnae: str | None = Field(max_length=20)
    uf: UF | None
    based_in_brazil: bool | None
    employee_count: int | None = Field(ge=1, le=2_000_000)
    fleet_size: int | None = Field(ge=1, le=500_000)
    sector: SectorFit
    sector_certainty: Certainty
    size_certainty: Certainty
    company_kind: CompanyKind
    area: Area
    seniority: Seniority
    role_certainty: Certainty
    intents: list[IntentSignal] = Field(max_length=5)
    flags: list[LeadFlag] = Field(max_length=5)
    evidence_ids: list[str] = Field(max_length=20)


class Assessment(BaseModel):
    """Saída do `assess_criteria`: só a justificativa (o LLM justifica, o código pontua)."""

    model_config = _STRICT

    rationale: str = Field(max_length=2000)
    cited_evidence: list[str] = Field(max_length=20)


@cache
def _sectors() -> SectorTaxonomy:
    return load_sector_taxonomy()


@cache
def _regions() -> RegionTaxonomy:
    return load_region_taxonomy()


def cnae_digits(cnae: str | None) -> str | None:
    """Dígitos do CNAE, se tiver pelo menos a classe (4 dígitos); senão `None`."""
    digits = re.sub(r"\D", "", cnae or "")
    return digits if len(digits) >= CNAE_MIN_DIGITS else None


def cnae_in_evidence(cnae: str | None, texts: Sequence[str]) -> bool:
    """O CNAE extraído aparece em alguma evidência? Barra CNAE inventado pelo LLM."""
    digits = cnae_digits(cnae)
    if digits is None:
        return False
    return any(digits in re.sub(r"\D", "", text) for text in texts)


def size_band(employees: int) -> SizeBand:
    if employees < 50:
        return SizeBand.S_1_49
    if employees < 200:
        return SizeBand.S_50_199
    if employees < 1000:
        return SizeBand.S_200_999
    return SizeBand.S_1000_PLUS


def to_profile(extraction: Extraction) -> LeadProfile:
    """Fatos + classificações → `LeadProfile`, com as regras de mapeamento do doc 02."""
    certainty: dict[Criterion, Certainty] = {Criterion.BUYING_ROLE: extraction.role_certainty}

    sector = extraction.sector
    sector_certainty = extraction.sector_certainty
    if cnae_digits(extraction.cnae):
        # CNAE é a fonte da "verdade" de setor. O nó só o mantém se ele aparecer nas evidências.
        sector, sector_certainty = _sectors().classify(extraction.cnae or ""), Certainty.HIGH
    certainty[Criterion.SECTOR] = sector_certainty

    if extraction.based_in_brazil is False:
        region = RegionFit.ABROAD
    else:
        region = _regions().classify(extraction.uf.value if extraction.uf else None)

    if extraction.employee_count:
        size = size_band(extraction.employee_count)
        certainty[Criterion.SIZE] = extraction.size_certainty
    elif extraction.fleet_size:
        size = size_band(round(extraction.fleet_size * EMPLOYEES_PER_VEHICLE))
        certainty[Criterion.SIZE] = Certainty.LOW
    else:
        size = SizeBand.UNKNOWN

    return LeadProfile(
        sector=sector,
        size=size,
        region=region,
        company_kind=extraction.company_kind,
        area=extraction.area,
        seniority=extraction.seniority,
        intents=frozenset(extraction.intents),
        flags=frozenset(extraction.flags),
        certainty=certainty,
    )


def confidence(profile: LeadProfile) -> float:
    """Confiança determinística: média das certezas de setor, porte e papel (0–1).

    Valor `unknown` pesa 0,2. Não é autodeclarada pelo LLM, que tende a superestimar.
    """
    values = {
        Criterion.SECTOR: profile.sector is SectorFit.UNKNOWN,
        Criterion.SIZE: profile.size is SizeBand.UNKNOWN,
        Criterion.BUYING_ROLE: profile.seniority is Seniority.UNKNOWN,
    }
    weights = [
        _UNKNOWN_WEIGHT
        if unknown
        else _CERTAINTY_WEIGHT[profile.certainty.get(criterion, Certainty.MEDIUM)]
        for criterion, unknown in values.items()
    ]
    return round(sum(weights) / len(weights), 3)
