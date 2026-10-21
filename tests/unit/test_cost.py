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
    # 8.000 × 0,75 + 2.000 × 0,075 + 1.500 × 4,50 = 6.000 + 150 + 6.750 = 12.900 → / 1M
    assert cost_usd(USAGE, get_catalog().get("openai-mini")) == Decimal("0.0129")


def test_cost_large_hand_computed() -> None:
    # 8.000 × 2,50 + 2.000 × 0,25 + 1.500 × 15 = 20.000 + 500 + 22.500 = 43.000 → / 1M
    assert cost_usd(USAGE, get_catalog().get("openai-large")) == Decimal("0.043")


def test_cost_embedding_and_local_slm() -> None:
    catalog = get_catalog()
    assert cost_usd(Usage(input_tokens=1_000_000), catalog.get("openai-embedding")) == Decimal(
        "0.02"
    )
    assert cost_usd(USAGE, catalog.get("ollama-slm")) == 0


def test_cost_is_exact_when_summing_many_calls() -> None:
    spec = get_catalog().get("openai-mini")
    one = Usage(input_tokens=1, output_tokens=1)
    total = sum((cost_usd(one, spec) for _ in range(1000)), Decimal(0))
    assert total == Decimal("0.00525")  # 1000 × (0,75 + 4,50) / 1M, sem erro de float


def test_usage_sum_and_consistency() -> None:
    assert (USAGE + USAGE).input_tokens == 20_000
    with pytest.raises(ValueError):
        Usage(input_tokens=10, cached_input_tokens=11)
    with pytest.raises(ValueError):
        Usage(output_tokens=1, reasoning_tokens=2)


def test_catalog_models_and_unknown_key() -> None:
    catalog = get_catalog()
    assert {
        "openai-mini",
        "openai-large",
        "openai-embedding",
        "ollama-slm",
    } <= catalog.models.keys()
    assert catalog.get("openai-mini").key == "openai-mini"
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
        ("openai-mini", {"model": "gpt-5.4-mini"}, "snapshot datado"),
        ("ollama-slm", {"model": "qwen3"}, "fixe a tag"),
        ("ollama-slm", {"model": "qwen3:latest"}, "fixe a tag"),
        ("ollama-slm", {"reasoning_effort": "low"}, "só existe na OpenAI"),
        ("openai-mini", {"price_per_1m": {"input": 1, "cached_input": 2, "output": 1}}, "cached"),
        ("openai-mini", {"price_per_1m": {"input": -1, "cached_input": 0, "output": 1}}, "input"),
        ("openai-mini", {"provider": "anthropic"}, "provider"),
        ("openai-mini", {"temperature": 0.2}, "temperature"),
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
