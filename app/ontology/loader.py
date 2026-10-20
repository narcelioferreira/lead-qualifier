"""Carrega e valida a rubrica e as taxonomias da ontologia.

Os YAMLs são lidos com `yaml.safe_load` (nunca `yaml.load`) e validados por modelos Pydantic:
qualquer inconsistência (peso que não soma 100, valor ontológico sem fator, UF faltando)
falha no carregamento, e não silenciosamente em produção.
"""

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ontology.models import (
    Area,
    BuyingRole,
    CompanyKind,
    Criterion,
    IntentSignal,
    LeadFlag,
    RegionFit,
    SectorFit,
    Seniority,
    SizeBand,
)
from app.schemas import Tier

ONTOLOGY_DIR = Path(__file__).parent
TAXONOMY_DIR = ONTOLOGY_DIR / "taxonomy"

BRAZIL_UFS = frozenset(
    {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
        "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }
)  # fmt: skip

# Conjunto de valores válidos por critério da rubrica.
CRITERION_VALUES: dict[Criterion, type[StrEnum]] = {
    Criterion.SECTOR: SectorFit,
    Criterion.BUYING_ROLE: BuyingRole,
    Criterion.SIZE: SizeBand,
    Criterion.INTENT: IntentSignal,
    Criterion.REGION: RegionFit,
}


class OntologyError(ValueError):
    """Rubrica ou taxonomia inválida."""


_STRICT = ConfigDict(extra="forbid", frozen=True)


class CriterionSpec(BaseModel):
    model_config = _STRICT

    weight: float = Field(gt=0)
    factors: dict[str, float]


class DisqualifierRule(BaseModel):
    model_config = _STRICT

    id: str
    reason: str
    flags: frozenset[LeadFlag] = frozenset()
    company_kind: frozenset[CompanyKind] = frozenset()
    sector: frozenset[SectorFit] = frozenset()
    region: frozenset[RegionFit] = frozenset()

    @model_validator(mode="after")
    def _has_condition(self) -> Self:
        if not (self.flags or self.company_kind or self.sector or self.region):
            raise ValueError(f"regra {self.id} não tem condição")
        return self


class CapRule(BaseModel):
    model_config = _STRICT

    id: str
    max_tier: Tier
    size: frozenset[SizeBand] = frozenset()
    buying_role: frozenset[BuyingRole] = frozenset()
    buying_role_not_in: frozenset[BuyingRole] = frozenset()

    @model_validator(mode="after")
    def _has_condition(self) -> Self:
        if not (self.size or self.buying_role or self.buying_role_not_in):
            raise ValueError(f"teto {self.id} não tem condição")
        if self.max_tier is Tier.D:
            raise ValueError("tetos não podem levar a D; use uma regra eliminatória")
        return self


class ReviewSpec(BaseModel):
    model_config = _STRICT

    critical_criteria: frozenset[Criterion]
    min_uncertain_to_review: int = Field(ge=1)


class Rubric(BaseModel):
    model_config = _STRICT

    version: int
    criteria: dict[Criterion, CriterionSpec]
    tiers: dict[Tier, float]
    borderline_margin: float = Field(ge=0)
    disqualifiers: tuple[DisqualifierRule, ...]
    caps: tuple[CapRule, ...]
    review: ReviewSpec

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        missing = set(Criterion) - set(self.criteria)
        if missing:
            raise ValueError(f"critérios sem especificação: {sorted(missing)}")
        total = sum(spec.weight for spec in self.criteria.values())
        if abs(total - 100) > 1e-9:
            raise ValueError(f"os pesos devem somar 100 (somam {total})")
        for criterion, spec in self.criteria.items():
            allowed = {v.value for v in CRITERION_VALUES[criterion]}
            if set(spec.factors) != allowed:
                raise ValueError(
                    f"fatores de '{criterion}' devem cobrir exatamente {sorted(allowed)}"
                )
            if any(not 0 <= f <= 1 for f in spec.factors.values()):
                raise ValueError(f"fatores de '{criterion}' devem estar entre 0 e 1")
        if set(self.tiers) != {Tier.A, Tier.B}:
            raise ValueError("tiers deve definir exatamente os limites de A e B")
        if not 0 < self.tiers[Tier.B] < self.tiers[Tier.A] <= 100:
            raise ValueError("limites de tier devem satisfazer 0 < B < A <= 100")
        ids = [r.id for r in self.disqualifiers] + [c.id for c in self.caps]
        if len(ids) != len(set(ids)):
            raise ValueError("IDs de regras duplicados")
        return self

    def points(self, criterion: Criterion, value: StrEnum) -> float:
        spec = self.criteria[criterion]
        return spec.weight * spec.factors[value.value]


class SectorTaxonomy(BaseModel):
    model_config = _STRICT

    version: int
    default: SectorFit
    prefixes: dict[str, SectorFit]

    @model_validator(mode="after")
    def _valid_prefixes(self) -> Self:
        for prefix in self.prefixes:
            if not re.fullmatch(r"\d{2,7}", prefix):
                raise ValueError(f"prefixo CNAE inválido: {prefix!r}")
        return self

    def classify(self, cnae: str) -> SectorFit:
        digits = re.sub(r"\D", "", cnae)
        if len(digits) < 2:
            return SectorFit.UNKNOWN
        for size in range(len(digits), 1, -1):
            match = self.prefixes.get(digits[:size])
            if match is not None:
                return match
        return self.default


class RegionTaxonomy(BaseModel):
    model_config = _STRICT

    version: int
    priority: frozenset[str]
    secondary: frozenset[str]

    @model_validator(mode="after")
    def _covers_brazil(self) -> Self:
        if self.priority & self.secondary:
            raise ValueError(f"UFs em duas listas: {sorted(self.priority & self.secondary)}")
        covered = self.priority | self.secondary
        if covered != BRAZIL_UFS:
            raise ValueError(
                f"as UFs devem cobrir o Brasil exatamente; faltam {sorted(BRAZIL_UFS - covered)}, "
                f"sobram {sorted(covered - BRAZIL_UFS)}"
            )
        return self

    def classify(self, uf: str | None, country: str = "BR") -> RegionFit:
        if country.upper() not in {"BR", "BRASIL", "BRAZIL"}:
            return RegionFit.ABROAD
        if not uf:
            return RegionFit.UNKNOWN
        code = uf.strip().upper()
        if code in self.priority:
            return RegionFit.PRIORITY
        if code in self.secondary:
            return RegionFit.SECONDARY
        return RegionFit.UNKNOWN


class BuyingRoleTable(BaseModel):
    model_config = _STRICT

    version: int
    area_groups: dict[str, frozenset[Area]]
    matrix: dict[Seniority, dict[str, BuyingRole]]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        all_areas = [a for group in self.area_groups.values() for a in group]
        if sorted(all_areas) != sorted(Area):
            raise ValueError("cada Área deve pertencer a exatamente um grupo")
        if set(self.matrix) != set(Seniority):
            raise ValueError("a matriz deve ter uma linha para cada Senioridade")
        for seniority, row in self.matrix.items():
            if set(row) != set(self.area_groups):
                raise ValueError(f"linha '{seniority}' deve cobrir todos os grupos de área")
        return self

    def derive(self, seniority: Seniority, area: Area) -> BuyingRole:
        group = next(name for name, areas in self.area_groups.items() if area in areas)
        return self.matrix[seniority][group]


def _read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyError(f"não foi possível ler {path.name}: {exc}") from exc


def _parse[M: BaseModel](model: type[M], path: Path) -> M:
    try:
        return model.model_validate(_read_yaml(path))
    except ValueError as exc:
        raise OntologyError(f"{path.name} inválido: {exc}") from exc


def load_rubric(path: Path | None = None) -> Rubric:
    return _parse(Rubric, path or ONTOLOGY_DIR / "rubric.yaml")


def load_sector_taxonomy(path: Path | None = None) -> SectorTaxonomy:
    return _parse(SectorTaxonomy, path or TAXONOMY_DIR / "sectors.yaml")


def load_region_taxonomy(path: Path | None = None) -> RegionTaxonomy:
    return _parse(RegionTaxonomy, path or TAXONOMY_DIR / "regions.yaml")


def load_buying_roles(path: Path | None = None) -> BuyingRoleTable:
    return _parse(BuyingRoleTable, path or TAXONOMY_DIR / "buying_roles.yaml")


@lru_cache
def default_rubric() -> Rubric:
    return load_rubric()


@lru_cache
def default_buying_roles() -> BuyingRoleTable:
    return load_buying_roles()
