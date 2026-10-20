from pathlib import Path

import pytest
import yaml

from app.ontology.loader import (
    ONTOLOGY_DIR,
    TAXONOMY_DIR,
    OntologyError,
    load_buying_roles,
    load_region_taxonomy,
    load_rubric,
    load_sector_taxonomy,
)
from app.ontology.models import Area, BuyingRole, Criterion, RegionFit, SectorFit, Seniority


def _write_variant(tmp_path: Path, source: Path, mutate: object) -> Path:
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    mutate(data)  # type: ignore[operator]
    target = tmp_path / source.name
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    return target


# --- Rubrica ---------------------------------------------------------------------------


def test_default_rubric_loads_and_weights_sum_100() -> None:
    rubric = load_rubric()
    assert sum(s.weight for s in rubric.criteria.values()) == 100
    assert set(rubric.criteria) == set(Criterion)


def test_rubric_points() -> None:
    rubric = load_rubric()
    assert rubric.points(Criterion.SECTOR, SectorFit.ADJACENT) == 15
    assert rubric.points(Criterion.BUYING_ROLE, BuyingRole.INFLUENCER) == 15


@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        ("pesos != 100", lambda d: d["criteria"]["sector"].update(weight=31)),
        ("fator faltando", lambda d: d["criteria"]["size"]["factors"].pop("1000+")),
        ("fator extra", lambda d: d["criteria"]["region"]["factors"].update(mars=1.0)),
        ("fator > 1", lambda d: d["criteria"]["intent"]["factors"].update(pain=1.5)),
        ("critério faltando", lambda d: d["criteria"].pop("region")),
        ("limites invertidos", lambda d: d.update(tiers={"A": 50, "B": 60})),
        ("valor ontológico inválido", lambda d: d["disqualifiers"][0].update(flags=["robot"])),
        ("regra sem condição", lambda d: d["caps"].append({"id": "C9", "max_tier": "B"})),
        ("teto para D", lambda d: d["caps"][0].update(max_tier="D")),
        ("id duplicado", lambda d: d["caps"][1].update(id="C1")),
        ("campo desconhecido", lambda d: d.update(bonus=10)),
    ],
)
def test_invalid_rubric_raises_clear_error(
    tmp_path: Path, description: str, mutate: object
) -> None:
    path = _write_variant(tmp_path, ONTOLOGY_DIR / "rubric.yaml", mutate)
    with pytest.raises(OntologyError, match=r"rubric\.yaml inválido"):
        load_rubric(path)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "rubric.yaml"
    path.write_text("criteria: [unclosed", encoding="utf-8")
    with pytest.raises(OntologyError, match="não foi possível ler"):
        load_rubric(path)


def test_unsafe_yaml_tags_are_not_executed(tmp_path: Path) -> None:
    # yaml.load inseguro executaria isso; safe_load deve recusar.
    path = tmp_path / "rubric.yaml"
    path.write_text("!!python/object/apply:os.system ['echo pwned']", encoding="utf-8")
    with pytest.raises(OntologyError):
        load_rubric(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OntologyError):
        load_rubric(tmp_path / "nao-existe.yaml")


# --- Papel na compra -------------------------------------------------------------------


def test_every_seniority_area_combination_has_a_buying_role() -> None:
    table = load_buying_roles()
    for seniority in Seniority:
        for area in Area:
            assert isinstance(table.derive(seniority, area), BuyingRole)


@pytest.mark.parametrize(
    ("seniority", "area", "expected"),
    [
        (Seniority.DIRECTOR, Area.OPERATIONS, BuyingRole.DECISION_MAKER),
        (Seniority.C_LEVEL, Area.FINANCE, BuyingRole.DECISION_MAKER),
        (Seniority.OWNER, Area.EXECUTIVE, BuyingRole.DECISION_MAKER),
        (Seniority.MANAGER, Area.LOGISTICS, BuyingRole.DECISION_MAKER),
        (Seniority.MANAGER, Area.FINANCE, BuyingRole.INFLUENCER),
        (Seniority.COORDINATOR, Area.FLEET, BuyingRole.INFLUENCER),
        (Seniority.DIRECTOR, Area.IT, BuyingRole.INFLUENCER),
        (Seniority.ANALYST, Area.PROCUREMENT, BuyingRole.USER),
        (Seniority.INTERN, Area.LOGISTICS, BuyingRole.NONE),
        (Seniority.C_LEVEL, Area.MARKETING, BuyingRole.NONE),
        (Seniority.UNKNOWN, Area.OPERATIONS, BuyingRole.UNKNOWN),
        (Seniority.UNKNOWN, Area.SALES, BuyingRole.NONE),
    ],
)
def test_buying_role_matrix_matches_spec(
    seniority: Seniority, area: Area, expected: BuyingRole
) -> None:
    assert load_buying_roles().derive(seniority, area) is expected


def test_incomplete_buying_role_matrix_rejected(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, TAXONOMY_DIR / "buying_roles.yaml", lambda d: d["matrix"].pop("intern")
    )
    with pytest.raises(OntologyError):
        load_buying_roles(path)


def test_area_in_two_groups_rejected(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path,
        TAXONOMY_DIR / "buying_roles.yaml",
        lambda d: d["area_groups"]["support"].append("finance"),
    )
    with pytest.raises(OntologyError):
        load_buying_roles(path)


# --- Setor (CNAE) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cnae", "expected"),
    [
        ("4930-2/02", SectorFit.TARGET),  # transporte rodoviário de carga
        ("4632-0/01", SectorFit.TARGET),  # atacado
        ("5211-7/99", SectorFit.ADJACENT),  # armazenagem
        ("4120-4/00", SectorFit.ADJACENT),  # construção
        ("7711-0/00", SectorFit.ADJACENT),  # locadora
        ("4921-3/01", SectorFit.OUT),  # transporte de passageiros: não é carga
        ("6201-5/01", SectorFit.OUT),  # software
        ("6421-2/00", SectorFit.OUT),  # banco
        ("", SectorFit.UNKNOWN),
        ("x", SectorFit.UNKNOWN),
    ],
)
def test_sector_by_cnae(cnae: str, expected: SectorFit) -> None:
    assert load_sector_taxonomy().classify(cnae) is expected


def test_invalid_cnae_prefix_rejected(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, TAXONOMY_DIR / "sectors.yaml", lambda d: d["prefixes"].update({"ab": "target"})
    )
    with pytest.raises(OntologyError):
        load_sector_taxonomy(path)


# --- Região ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("uf", "country", "expected"),
    [
        ("SP", "BR", RegionFit.PRIORITY),
        ("df", "BR", RegionFit.PRIORITY),
        ("BA", "BR", RegionFit.SECONDARY),
        (None, "BR", RegionFit.UNKNOWN),
        ("XX", "BR", RegionFit.UNKNOWN),
        ("SP", "PT", RegionFit.ABROAD),
    ],
)
def test_region(uf: str | None, country: str, expected: RegionFit) -> None:
    assert load_region_taxonomy().classify(uf, country) is expected


def test_regions_must_cover_all_ufs(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, TAXONOMY_DIR / "regions.yaml", lambda d: d["secondary"].remove("BA")
    )
    with pytest.raises(OntologyError, match="faltam"):
        load_region_taxonomy(path)


def test_uf_in_both_lists_rejected(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, TAXONOMY_DIR / "regions.yaml", lambda d: d["priority"].append("BA")
    )
    with pytest.raises(OntologyError, match="duas listas"):
        load_region_taxonomy(path)
