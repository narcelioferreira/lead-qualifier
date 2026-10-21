from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.routing.cost import (
    MODELS_PATH,
    CatalogError,
    Usage,
    cost_usd,
    get_catalog,
    load_catalog,
)

# Uso de referência: 10.000 tokens de entrada (2.000 em cache) e 1.500 de saída (500 de raciocínio).
USAGE = Usage(input_tokens=10_000, cached_input_tokens=2_000, output_tokens=1_500,
              reasoning_tokens=500)  # fmt: skip


def test_cost_mini_hand_computed() -> None:
    # 8.000 × 0,075 + 2.000 × 0,037 + 1.500 × 0,30 = 600 + 74 + 450 = 1.124 → / 1M
    assert cost_usd(USAGE, get_catalog().get("groq-mini")) == Decimal("0.001124")


def test_cost_large_hand_computed() -> None:
    # 8.000 × 0,15 + 2.000 × 0,075 + 1.500 × 0,60 = 1.200 + 150 + 900 = 2.250 → / 1M
    assert cost_usd(USAGE, get_catalog().get("groq-large")) == Decimal("0.00225")


def test_cost_local_models_is_zero() -> None:
    catalog = get_catalog()
    assert cost_usd(USAGE, catalog.get("ollama-slm")) == 0
    assert cost_usd(Usage(input_tokens=1_000_000), catalog.get("ollama-embedding")) == 0


def test_cost_is_exact_when_summing_many_calls() -> None:
    spec = get_catalog().get("groq-mini")
    one = Usage(input_tokens=1, output_tokens=1)
    total = sum((cost_usd(one, spec) for _ in range(1000)), Decimal(0))
    assert total == Decimal("0.000375")  # 1000 × (0,075 + 0,30) / 1M, sem erro de float


def test_usage_sum_and_consistency() -> None:
    assert (USAGE + USAGE).input_tokens == 20_000
    with pytest.raises(ValueError):
        Usage(input_tokens=10, cached_input_tokens=11)
    with pytest.raises(ValueError):
        Usage(output_tokens=1, reasoning_tokens=2)


def test_catalog_models_and_unknown_key() -> None:
    catalog = get_catalog()
    assert {
        "groq-mini",
        "groq-large",
        "ollama-slm",
        "ollama-embedding",
    } <= catalog.models.keys()
    assert catalog.get("groq-mini").key == "groq-mini"
    with pytest.raises(CatalogError, match="desconhecido"):
        catalog.get("gpt-qualquer")


def _variant(tmp_path: Path, key: str, **changes: object) -> Path:
    data = yaml.safe_load(MODELS_PATH.read_text(encoding="utf-8"))
    data["models"][key].update(changes)
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("key", "changes", "match"),
    [
        ("groq-mini", {"model": "qwen/qwen3-32b-preview"}, "versão móvel"),
        ("ollama-slm", {"model": "qwen3:latest"}, "versão móvel"),
        ("ollama-slm", {"model": "qwen3"}, "fixe a tag"),
        ("ollama-slm", {"reasoning_effort": "low"}, "não se aplica"),
        ("groq-mini", {"reasoning_effort": "xhigh"}, "reasoning_effort"),
        ("groq-mini", {"price_per_1m": {"input": 1, "cached_input": 2, "output": 1}}, "cached"),
        ("groq-mini", {"price_per_1m": {"input": -1, "cached_input": 0, "output": 1}}, "input"),
        ("groq-mini", {"provider": "openai"}, "provider"),
        ("groq-mini", {"temperature": 0.2}, "temperature"),
        ("groq-mini", {"think": False}, "think só se aplica"),
    ],
)
def test_invalid_catalog_raises(tmp_path: Path, key: str, changes: dict[str, object],
                                match: str) -> None:  # fmt: skip
    with pytest.raises(CatalogError, match=match):
        load_catalog(_variant(tmp_path, key, **changes))


def test_catalog_uses_safe_load(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text("!!python/object/apply:os.system ['echo pwned']\n", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path)
