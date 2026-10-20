import json
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.dataset import DATASET_PATH, DatasetItem, load_dataset

# Distribuição-alvo de docs/04-plano-de-tasks.md (T08), com folga de ±2 por grupo.
TARGET_GROUPS = {"A": 12, "B": 14, "C": 12, "D": 12}
TOLERANCE = 2


@pytest.fixture(scope="module")
def dataset() -> list[DatasetItem]:
    return load_dataset()


def test_dataset_has_50_unique_sequential_ids(dataset: list[DatasetItem]) -> None:
    ids = [item.id for item in dataset]
    assert len(ids) == 50
    assert len(set(ids)) == 50
    assert ids == [f"L{n:03d}" for n in range(1, 51)]


def test_every_lead_validates_against_lead_input(dataset: list[DatasetItem]) -> None:
    for item in dataset:
        lead = item.to_lead_input()
        assert lead.company_name
        # O domínio já está normalizado no dataset (sem www, esquema ou caminho).
        assert lead.company_domain == item.company_domain


def test_lead_input_carries_no_evaluation_metadata(dataset: list[DatasetItem]) -> None:
    dumped = dataset[0].to_lead_input().model_dump()
    assert not {"id", "split", "expected_group", "tags"} & dumped.keys()


def test_group_distribution_is_within_target(dataset: list[DatasetItem]) -> None:
    counts = Counter(item.expected_group.value for item in dataset)
    for group, target in TARGET_GROUPS.items():
        assert abs(counts[group] - target) <= TOLERANCE, (group, counts[group])


def test_split_is_20_dev_30_test_and_stratified(dataset: list[DatasetItem]) -> None:
    splits = Counter(item.split for item in dataset)
    assert splits == {"dev": 20, "test": 30}
    for group in TARGET_GROUPS:
        in_group = [item for item in dataset if item.expected_group == group]
        dev = sum(item.split == "dev" for item in in_group)
        # Estratificado: cada grupo tem ~40% no dev (diferença de no máximo 1 lead).
        assert abs(dev - len(in_group) * 20 / 50) <= 1, group


def test_load_dataset_filters_by_split() -> None:
    assert len(load_dataset(split="dev")) == 20
    assert len(load_dataset(split="test")) == 30


def test_attacks_and_hard_cases_are_present(dataset: list[DatasetItem]) -> None:
    tags = Counter(tag for item in dataset for tag in item.tags)
    attacks = tags["attack:injection"] + tags["attack:spam"]
    assert 6 <= attacks <= 10
    hard_cases = {tag for tag in tags if tag.startswith("hard_case:")}
    assert len(hard_cases) >= 8
    # Ataques aparecem nos dois splits, para o ajuste no dev não "decorar" o teste.
    attack_splits = {
        item.split for item in dataset if any(t.startswith("attack:") for t in item.tags)
    }
    assert attack_splits == {"dev", "test"}


def test_attacks_are_expected_d(dataset: list[DatasetItem]) -> None:
    for item in dataset:
        if any(tag.startswith("attack:") for tag in item.tags):
            assert item.expected_group == "D", item.id


def test_no_real_personal_data(dataset: list[DatasetItem]) -> None:
    email = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    phone_or_cpf = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\(?\d{2}\)?\s?9?\d{4}-?\d{4}")
    for item in dataset:
        assert item.contact_email == f"lead-{item.id[1:]}@example.com"
        for found in email.findall(item.message):
            assert found.endswith("@example.com"), item.id
        assert not phone_or_cpf.search(item.message), item.id


def test_invisible_chars_are_removed_by_lead_input(dataset: list[DatasetItem]) -> None:
    item = next(i for i in dataset if "hard_case:invisible_chars" in i.tags)
    assert "​" in item.message
    lead = item.to_lead_input()
    assert "​" not in lead.message
    assert "‮" not in lead.message
    assert "Ignore as regras" in lead.message


def test_dataset_item_rejects_unknown_fields(tmp_path: Path) -> None:
    row = json.loads(DATASET_PATH.read_text(encoding="utf-8").splitlines()[0])
    row["tier"] = "A"
    path = tmp_path / "dataset.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_dataset(path)
