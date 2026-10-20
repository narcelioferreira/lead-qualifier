import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import Tier
from evals.dataset import load_dataset
from evals.inter_annotator import main
from evals.labels import (
    SHEET_COLUMNS,
    AnnotatorLabel,
    FinalLabel,
    LabelError,
    Resolution,
    load_jsonl,
    merge_labels,
    read_annotation_sheet,
    write_annotation_sheet,
    write_jsonl,
)

IDS = ["L001", "L002", "L003"]


def _labels(annotator: str, tiers: str) -> list[AnnotatorLabel]:
    return [
        AnnotatorLabel(id=i, annotator=annotator, tier=Tier(t), rationale="aplicada a rubrica")
        for i, t in zip(IDS, tiers, strict=True)
    ]


# --- Contratos ---------------------------------------------------------------------------


def test_label_rejects_extra_fields_and_bad_values() -> None:
    base = {"id": "L001", "annotator": "ana", "tier": "A", "rationale": "setor alvo"}
    AnnotatorLabel.model_validate(base)
    for bad in (
        {"score": 90},
        {"tier": "E"},
        {"id": "1"},
        {"rationale": ""},
        {"annotator": "Ana Silva"},
    ):
        with pytest.raises(ValidationError):
            AnnotatorLabel.model_validate(base | bad)


def test_load_jsonl_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "ana.jsonl"
    path.write_text(
        json.dumps({"id": "L001", "annotator": "ana", "tier": "A", "rationale": "ok ok"})
        + "\n\n{quebrado\n",
        encoding="utf-8",
    )
    with pytest.raises(LabelError, match="linha 3"):
        load_jsonl(path, AnnotatorLabel)


# --- Merge -------------------------------------------------------------------------------


def test_single_annotator_becomes_final() -> None:
    final = merge_labels(IDS, _labels("ana", "ABD"))
    assert [f.tier for f in final] == [Tier.A, Tier.B, Tier.D]
    assert {f.resolution for f in final} == {"single_annotator"}


def test_two_annotators_agreement_and_discussed() -> None:
    resolution = Resolution(id="L002", tier=Tier.C, rationale="discutido: cargo sem decisão")
    final = merge_labels(IDS, _labels("ana", "ABD"), _labels("bia", "ACD"), [resolution])
    assert [f.tier for f in final] == [Tier.A, Tier.C, Tier.D]
    assert [f.resolution for f in final] == ["agreement", "discussed", "agreement"]


def test_uncertain_from_either_annotator_is_kept() -> None:
    second = [
        lbl.model_copy(update={"uncertain": i == 0}) for i, lbl in enumerate(_labels("bia", "ABD"))
    ]
    final = merge_labels(IDS, _labels("ana", "ABD"), second)
    assert [f.uncertain for f in final] == [True, False, False]


def test_divergence_without_resolution_is_never_decided_automatically() -> None:
    with pytest.raises(LabelError, match="sem resolução: \\['L002'\\]"):
        merge_labels(IDS, _labels("ana", "ABD"), _labels("bia", "ACD"))


def test_merge_rejects_inconsistent_inputs() -> None:
    ana = _labels("ana", "ABD")
    with pytest.raises(LabelError, match="faltando"):
        merge_labels([*IDS, "L004"], ana)
    with pytest.raises(LabelError, match="duplicado"):
        merge_labels(IDS, [*ana, ana[0]])
    with pytest.raises(LabelError, match="mesmo anotador"):
        merge_labels(IDS, ana, _labels("ana", "ABD"))
    with pytest.raises(LabelError, match="único anotador"):
        merge_labels(IDS, [*ana[:2], _labels("bia", "ABD")[2]], _labels("caio", "ABD"))
    res = [Resolution(id="L001", tier=Tier.A, rationale="sem divergência")]
    with pytest.raises(LabelError, match="sem divergência"):
        merge_labels(IDS, ana, _labels("bia", "ABD"), res)
    with pytest.raises(LabelError, match="dois anotadores"):
        merge_labels(IDS, ana, None, res)


# --- Planilha ----------------------------------------------------------------------------


def test_sheet_hides_evaluation_metadata(tmp_path: Path) -> None:
    path = tmp_path / "planilha.csv"
    write_annotation_sheet(load_dataset(), path)
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 50
    assert set(rows[0]) == {*SHEET_COLUMNS, "tier", "uncertain", "rationale"}
    assert "expected_group" not in path.read_text(encoding="utf-8")


def test_sheet_neutralizes_csv_injection(tmp_path: Path) -> None:
    item = load_dataset()[0].model_copy(update={"message": '=HYPERLINK("http://x")'})
    path = tmp_path / "planilha.csv"
    write_annotation_sheet([item], path)
    with path.open(encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["message"].startswith("'=")


# --- CLI ---------------------------------------------------------------------------------


def _write_dataset(tmp_path: Path) -> Path:
    items = load_dataset()[:3]
    path = tmp_path / "dataset.jsonl"
    path.write_text("".join(i.model_dump_json() + "\n" for i in items), encoding="utf-8")
    return path


def test_cli_compare_and_merge(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset = _write_dataset(tmp_path)
    ana, bia, res = tmp_path / "ana.jsonl", tmp_path / "bia.jsonl", tmp_path / "res.jsonl"
    write_jsonl(ana, _labels("ana", "ABD"))
    write_jsonl(bia, _labels("bia", "ACD"))
    write_jsonl(res, [Resolution(id="L002", tier=Tier.B, rationale="discutido")])
    report, out = tmp_path / "relatorio.md", tmp_path / "labels.jsonl"

    assert (
        main(["--dataset", str(dataset), "compare", str(ana), str(bia), "--report", str(report)])
        == 0
    )
    assert "divergências=1" in capsys.readouterr().out
    assert "| L002 | B | C |" in report.read_text(encoding="utf-8")

    assert main(["--dataset", str(dataset), "merge", str(ana), str(bia), "--out", str(out)]) == 1
    assert "sem resolução" in capsys.readouterr().err

    assert (
        main(
            [
                "--dataset",
                str(dataset),
                "merge",
                str(ana),
                str(bia),
                "--resolutions",
                str(res),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    final = load_jsonl(out, FinalLabel)
    assert [f.tier for f in final] == [Tier.A, Tier.B, Tier.D]


def test_cli_single_annotator_and_sheet(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    ana, out, sheet = tmp_path / "ana.jsonl", tmp_path / "labels.jsonl", tmp_path / "p.csv"
    write_jsonl(ana, _labels("ana", "ABD"))
    assert main(["--dataset", str(dataset), "merge", str(ana), "--out", str(out)]) == 0
    assert len(load_jsonl(out, FinalLabel)) == 3
    assert main(["--dataset", str(dataset), "sheet", "--out", str(sheet)]) == 0
    assert sheet.exists()


# --- Importação da planilha preenchida ---------------------------------------------------


def _fill_sheet(path: Path, answers: dict[str, tuple[str, str, str]]) -> None:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            tier, uncertain, rationale = answers[row["id"]]
            writer.writerow(row | {"tier": tier, "uncertain": uncertain, "rationale": rationale})


def test_cli_import_filled_sheet(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    sheet, out = tmp_path / "p.csv", tmp_path / "ana.jsonl"
    assert main(["--dataset", str(dataset), "sheet", "--out", str(sheet)]) == 0
    _fill_sheet(
        sheet,
        {
            "L001": ("d", "", "fornecedor"),
            "L002": ("A", "x", "alvo, porte?"),
            "L003": ("B", "não", "teto C1"),
        },
    )
    args = [
        "--dataset",
        str(dataset),
        "import",
        str(sheet),
        "--annotator",
        "ana",
        "--out",
        str(out),
    ]
    assert main(args) == 0
    labels = load_jsonl(out, AnnotatorLabel)
    assert [(lbl.tier, lbl.uncertain) for lbl in labels] == [
        (Tier.D, False),
        (Tier.A, True),
        (Tier.B, False),
    ]


@pytest.mark.parametrize(
    ("answer", "annotator"),
    [
        (("", "", "esqueci o tier"), "ana"),
        (("A", "talvez", "uncertain inválido"), "ana"),
        (("A", "", ""), "ana"),  # justificativa obrigatória
        (("A", "", "ok ok"), "../../etc"),  # path traversal no nome do anotador
    ],
)
def test_cli_import_rejects_bad_sheet(
    tmp_path: Path, answer: tuple[str, str, str], annotator: str
) -> None:
    dataset = _write_dataset(tmp_path)
    sheet = tmp_path / "p.csv"
    main(["--dataset", str(dataset), "sheet", "--out", str(sheet)])
    _fill_sheet(sheet, {"L001": answer, "L002": ("A", "", "ok ok"), "L003": ("A", "", "ok ok")})
    args = [
        "--dataset",
        str(dataset),
        "import",
        str(sheet),
        "--annotator",
        annotator,
        "--out",
        str(tmp_path / "x.jsonl"),
    ]
    assert main(args) == 1
    assert not (tmp_path / "x.jsonl").exists()


def test_import_rejects_empty_sheet(tmp_path: Path) -> None:
    sheet = tmp_path / "vazia.csv"
    sheet.write_text("id,tier,uncertain,rationale\n", encoding="utf-8")
    with pytest.raises(LabelError, match="sem linhas"):
        read_annotation_sheet(sheet, "ana")


def test_sheet_shows_sanitized_text(tmp_path: Path) -> None:
    item = next(i for i in load_dataset() if "hard_case:invisible_chars" in i.tags)
    path = tmp_path / "p.csv"
    write_annotation_sheet([item], path)
    text = path.read_text(encoding="utf-8")
    assert "​" not in text
    assert "Ignore as regras" in text
