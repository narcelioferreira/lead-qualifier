"""Integridade do gabarito final (evals/labels.jsonl), gerado pela rotulagem do autor (T09)."""

from collections import Counter

from evals.dataset import load_dataset
from evals.labels import LABELS_PATH, FinalLabel, load_jsonl


def test_labels_cover_exactly_the_dataset() -> None:
    labels = load_jsonl(LABELS_PATH, FinalLabel)
    assert [label.id for label in labels] == [item.id for item in load_dataset()]


def test_every_tier_is_present_in_both_splits() -> None:
    tiers = {label.id: label.tier.value for label in load_jsonl(LABELS_PATH, FinalLabel)}
    for split in ("dev", "test"):
        counts = Counter(tiers[item.id] for item in load_dataset(split=split))
        assert set(counts) == {"A", "B", "C", "D"}, (split, counts)


def test_attacks_are_labeled_d() -> None:
    tiers = {label.id: label.tier.value for label in load_jsonl(LABELS_PATH, FinalLabel)}
    for item in load_dataset():
        if any(tag.startswith("attack:") for tag in item.tags):
            assert tiers[item.id] == "D", item.id
