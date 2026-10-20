"""Rótulos humanos do dataset (T09).

Fluxo: cada anotador preenche `evals/annotations/<anotador>.jsonl` (`AnnotatorLabel`) a partir
da planilha sem metadados, o kappa é calculado (`evals/agreement.py`), as divergências são
discutidas e registradas num arquivo de resoluções, e `merge_labels` gera o `labels.jsonl`
final (`FinalLabel`). Quem rotula é o autor: o código só valida e consolida.
"""

import csv
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Tier
from evals.dataset import DatasetItem

LABELS_PATH = Path(__file__).parent / "labels.jsonl"

Rationale = Field(min_length=3, max_length=500)
_ANNOTATOR = re.compile(r"^[a-z0-9_-]{1,40}$")

# Colunas da planilha de anotação. Ficam de fora `expected_group` e `tags`, para o grupo-alvo
# da montagem não enviesar o anotador.
SHEET_COLUMNS = ("id", "company_name", "company_domain", "contact_role", "message", "source")
# Prefixos que planilhas interpretam como fórmula (CSV injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_ANSWER_COLUMNS = ("tier", "uncertain", "rationale")
_TRUE = {"1", "x", "sim", "s", "true"}
_FALSE = {"", "0", "nao", "não", "n", "false"}


class LabelError(ValueError):
    """Arquivo de rótulos inconsistente com o dataset."""


class AnnotatorLabel(BaseModel):
    """Rótulo de um anotador para um lead."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^L\d{3}$")
    annotator: str = Field(pattern=_ANNOTATOR.pattern)
    tier: Tier
    uncertain: bool = False
    rationale: str = Rationale


class Resolution(BaseModel):
    """Decisão tomada após a discussão de uma divergência."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^L\d{3}$")
    tier: Tier
    rationale: str = Rationale


class FinalLabel(BaseModel):
    """Rótulo final usado na avaliação (`labels.jsonl`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^L\d{3}$")
    tier: Tier
    uncertain: bool = False
    rationale: str = Rationale
    resolution: Literal["agreement", "discussed", "single_annotator"]


def load_jsonl[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    """Lê um JSONL validando cada linha. O erro informa o número da linha."""
    rows: list[M] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(model.model_validate(json.loads(line)))
        except ValueError as exc:
            raise LabelError(f"{path.name}, linha {number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (row.model_dump_json() for row in rows)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def index_by_id[T: AnnotatorLabel | Resolution](
    rows: Sequence[T], expected_ids: Sequence[str] | None = None
) -> dict[str, T]:
    """Indexa por `id`, rejeitando duplicados e, se informado, IDs faltando ou sobrando."""
    index: dict[str, T] = {}
    for row in rows:
        if row.id in index:
            raise LabelError(f"id duplicado: {row.id}")
        index[row.id] = row
    if expected_ids is not None:
        missing = sorted(set(expected_ids) - index.keys())
        extra = sorted(index.keys() - set(expected_ids))
        if missing or extra:
            raise LabelError(f"ids não batem com o dataset: faltando={missing} sobrando={extra}")
    return index


def check_single_annotator(rows: Sequence[AnnotatorLabel]) -> str:
    names = {row.annotator for row in rows}
    if len(names) != 1:
        raise LabelError(f"o arquivo deve ter um único anotador, encontrado: {sorted(names)}")
    return names.pop()


def merge_labels(
    dataset_ids: Sequence[str],
    first: Sequence[AnnotatorLabel],
    second: Sequence[AnnotatorLabel] | None = None,
    resolutions: Sequence[Resolution] = (),
) -> list[FinalLabel]:
    """Consolida os rótulos finais.

    Com um anotador, o rótulo dele vira o final. Com dois, a concordância vira o final e
    cada divergência exige uma resolução registrada (nada é decidido automaticamente).
    """
    a = index_by_id(first, dataset_ids)
    b = index_by_id(second, dataset_ids) if second is not None else None
    resolved = index_by_id(resolutions)
    if b is not None:
        if check_single_annotator(first) == check_single_annotator(second or []):
            raise LabelError("os dois arquivos são do mesmo anotador")
        divergent = {i for i in dataset_ids if a[i].tier != b[i].tier}
        missing = sorted(divergent - resolved.keys())
        if missing:
            raise LabelError(f"divergências sem resolução: {missing}")
        unused = sorted(resolved.keys() - divergent)
        if unused:
            raise LabelError(f"resoluções para leads sem divergência: {unused}")
    elif resolved:
        raise LabelError("resoluções só fazem sentido com dois anotadores")

    final: list[FinalLabel] = []
    for lead_id in dataset_ids:
        label = a[lead_id]
        if b is None:
            final.append(_final(label, "single_annotator"))
        elif lead_id in resolved:
            res = resolved[lead_id]
            final.append(
                FinalLabel(
                    id=lead_id, tier=res.tier, rationale=res.rationale, resolution="discussed"
                )
            )
        else:
            other = b[lead_id]
            final.append(_final(label, "agreement", uncertain=label.uncertain or other.uncertain))
    return final


def _final(
    label: AnnotatorLabel,
    resolution: Literal["agreement", "single_annotator"],
    uncertain: bool | None = None,
) -> FinalLabel:
    return FinalLabel(
        id=label.id,
        tier=label.tier,
        uncertain=label.uncertain if uncertain is None else uncertain,
        rationale=label.rationale,
        resolution=resolution,
    )


def _safe_cell(value: str | None) -> str:
    """Neutraliza CSV injection: o texto do lead é não confiável e a planilha abre no Excel."""
    text = value or ""
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def write_annotation_sheet(items: Sequence[DatasetItem], path: Path) -> None:
    """Gera a planilha do anotador, sem o grupo-alvo nem as tags do dataset.

    O texto sai já sanitizado pelo `LeadInput`, igual ao que o agente recebe.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([*SHEET_COLUMNS, *_ANSWER_COLUMNS])
        for item in items:
            row = {"id": item.id, **item.to_lead_input().model_dump(mode="json")}
            writer.writerow([_safe_cell(row[col]) for col in SHEET_COLUMNS] + ["", "", ""])


def read_annotation_sheet(path: Path, annotator: str) -> list[AnnotatorLabel]:
    """Converte a planilha preenchida em rótulos validados (linhas sem tier são rejeitadas)."""
    if not _ANNOTATOR.fullmatch(annotator):
        # O nome vira nome de arquivo em `annotations/`: nada de "../" ou espaços.
        raise LabelError("anotador deve ter só letras minúsculas, dígitos, '_' ou '-'")
    labels: list[AnnotatorLabel] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for number, row in enumerate(csv.DictReader(fh), start=2):
            uncertain = (row.get("uncertain") or "").strip().lower()
            if uncertain not in _TRUE | _FALSE:
                raise LabelError(f"{path.name}, linha {number}: uncertain inválido: {uncertain!r}")
            try:
                labels.append(
                    AnnotatorLabel(
                        id=(row.get("id") or "").strip(),
                        annotator=annotator,
                        tier=Tier((row.get("tier") or "").strip().upper()),
                        uncertain=uncertain in _TRUE,
                        rationale=(row.get("rationale") or "").strip(),
                    )
                )
            except ValueError as exc:
                raise LabelError(f"{path.name}, linha {number}: {exc}") from exc
    if not labels:
        raise LabelError(f"{path.name}: planilha sem linhas")
    return labels
