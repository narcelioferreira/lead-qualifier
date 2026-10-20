"""Dataset de avaliação (ver docs/05-fontes-do-dataset.md).

Cada linha de `dataset.jsonl` traz os campos do `LeadInput` e metadados de avaliação
(`id`, `split`, `expected_group`, `tags`). Só o `LeadInput` chega ao agente: os metadados
ficam com o runner de avaliação, e os rótulos humanos ficam em `labels.jsonl` (T09).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import LeadInput, LeadSource, Tier

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"

Split = Literal["dev", "test"]

_LEAD_FIELDS = tuple(LeadInput.model_fields)


class DatasetItem(BaseModel):
    """Uma linha do dataset. Os campos do lead são validados de novo por `to_lead_input`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^L\d{3}$")
    split: Split
    # Grupo-alvo usado para montar e estratificar o dataset. Não é o rótulo (T09).
    expected_group: Tier
    company_name: str
    company_domain: str | None = None
    contact_role: str
    contact_email: str | None = None
    message: str = ""
    source: LeadSource
    tags: list[str] = Field(default_factory=list)

    def to_lead_input(self) -> LeadInput:
        """Monta a entrada do agente, sem nenhum metadado de avaliação."""
        return LeadInput.model_validate(self.model_dump(include=set(_LEAD_FIELDS)))


def load_dataset(path: Path = DATASET_PATH, split: Split | None = None) -> list[DatasetItem]:
    """Carrega e valida o dataset, opcionalmente filtrando por split."""
    items = [
        DatasetItem.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [item for item in items if split is None or item.split == split]
