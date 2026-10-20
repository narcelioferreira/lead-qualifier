"""CLI da rotulagem humana (T09). Executado por `scripts/inter_annotator.py`.

sheet    gera a planilha do anotador (sem grupo-alvo nem tags)
compare  calcula o kappa entre dois anotadores e gera o relatório em Markdown
merge    consolida o rótulo final (`labels.jsonl`) a partir das anotações e resoluções
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.agreement import agreement_report, render_markdown
from evals.dataset import DATASET_PATH, load_dataset
from evals.labels import (
    LABELS_PATH,
    AnnotatorLabel,
    LabelError,
    Resolution,
    check_single_annotator,
    index_by_id,
    load_jsonl,
    merge_labels,
    read_annotation_sheet,
    write_annotation_sheet,
    write_jsonl,
)

ANNOTATIONS_DIR = DATASET_PATH.parent / "annotations"
REPORT_PATH = DATASET_PATH.parent / "reports" / "00-concordancia-humana.md"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rotulagem humana e concordância (T09)")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    sheet = sub.add_parser("sheet", help="gera a planilha de anotação")
    sheet.add_argument("--out", type=Path, default=ANNOTATIONS_DIR / "planilha.csv")

    imp = sub.add_parser("import", help="converte a planilha preenchida em JSONL")
    imp.add_argument("sheet", type=Path)
    imp.add_argument("--annotator", required=True)
    imp.add_argument("--out", type=Path)

    compare = sub.add_parser("compare", help="kappa entre dois anotadores")
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    compare.add_argument("--report", type=Path, default=REPORT_PATH)

    merge = sub.add_parser("merge", help="gera o labels.jsonl final")
    merge.add_argument("first", type=Path)
    merge.add_argument("second", type=Path, nargs="?")
    merge.add_argument("--resolutions", type=Path)
    merge.add_argument("--out", type=Path, default=LABELS_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ids = [item.id for item in load_dataset(args.dataset)]
    try:
        if args.command == "sheet":
            write_annotation_sheet(load_dataset(args.dataset), args.out)
            print(f"planilha gerada: {args.out}")
        elif args.command == "import":
            labels = read_annotation_sheet(args.sheet, args.annotator)
            index_by_id(labels, ids)
            out = args.out or ANNOTATIONS_DIR / f"{args.annotator}.jsonl"
            write_jsonl(out, labels)
            print(f"{len(labels)} rótulos de {args.annotator} gravados em {out}")
        elif args.command == "compare":
            first = load_jsonl(args.first, AnnotatorLabel)
            second = load_jsonl(args.second, AnnotatorLabel)
            a, b = index_by_id(first, ids), index_by_id(second, ids)
            names = (check_single_annotator(first), check_single_annotator(second))
            report = agreement_report(
                ids, [a[i].tier for i in ids], [b[i].tier for i in ids], names
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_markdown(report), encoding="utf-8")
            print(
                f"kappa={report.kappa:.3f} kappa_linear={report.kappa_linear:.3f} "
                f"divergências={len(report.divergences)} relatório={args.report}"
            )
        else:
            labels = load_jsonl(args.first, AnnotatorLabel)
            others = load_jsonl(args.second, AnnotatorLabel) if args.second else None
            resolutions = load_jsonl(args.resolutions, Resolution) if args.resolutions else []
            final = merge_labels(ids, labels, others, resolutions)
            write_jsonl(args.out, final)
            print(f"{len(final)} rótulos finais gravados em {args.out}")
    except LabelError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0
