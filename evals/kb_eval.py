"""Hit rate@k da busca na base de conhecimento (T24).

`evals/kb_questions.jsonl` tem 10 perguntas, cada uma com o documento que deveria aparecer
entre os k primeiros resultados. São medidos dois modos:
- **com filtro**: como o agente vai usar (tipo de documento, tier e setor da ontologia);
- **sem filtro**: só a similaridade vetorial, para saber quanto o filtro está ajudando.

Uso (com a base já indexada por `scripts/ingest_kb.py`):
    uv run python -m evals.kb_eval [--k 3] [--report evals/reports/kb-retrieval.md]
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.knowledge_base import DocId
from tools_mcp.kb import KBFilters, KnowledgeBaseSearch

QUESTIONS_PATH = Path(__file__).parent / "kb_questions.jsonl"
TARGET_HIT_RATE = 0.8


class KBQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    expected_doc_id: DocId
    filters: KBFilters = KBFilters()


@dataclass(frozen=True)
class QuestionResult:
    question: KBQuestion
    retrieved: list[str]  # doc_ids, em ordem

    @property
    def rank(self) -> int | None:
        doc_id = self.question.expected_doc_id
        return self.retrieved.index(doc_id) + 1 if doc_id in self.retrieved else None


@dataclass(frozen=True)
class KBEvalReport:
    k: int
    filtered: bool
    results: list[QuestionResult]

    @property
    def hits(self) -> int:
        return sum(1 for r in self.results if r.rank is not None)

    @property
    def hit_rate(self) -> float:
        return self.hits / len(self.results) if self.results else 0.0

    @property
    def mrr(self) -> float:
        """Mean reciprocal rank: 1 se o esperado vem sempre em 1º, 0,5 se vem em 2º..."""
        ranks = [r.rank for r in self.results]
        return sum(1 / r for r in ranks if r) / len(ranks) if ranks else 0.0


def load_questions(path: Path = QUESTIONS_PATH) -> list[KBQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    questions = [KBQuestion.model_validate(json.loads(line)) for line in lines if line.strip()]
    if len({q.id for q in questions}) != len(questions):
        raise ValueError("ids de pergunta repetidos")
    return questions


async def evaluate(
    search: KnowledgeBaseSearch, questions: list[KBQuestion], *, k: int = 3, filtered: bool
) -> KBEvalReport:
    results = []
    for q in questions:
        found = await search.search(q.question, q.filters if filtered else None, k=k)
        results.append(QuestionResult(q, [hit.doc_id for hit in found.results]))
    return KBEvalReport(k=k, filtered=filtered, results=results)


def render(reports: list[KBEvalReport]) -> str:
    lines = ["# Busca na base de conhecimento: hit rate", ""]
    lines += ["| Modo | Hit rate@k | Acertos | MRR |", "|---|---:|---:|---:|"]
    for rep in reports:
        mode = "com filtro" if rep.filtered else "sem filtro"
        lines.append(
            f"| {mode} | {rep.hit_rate:.0%} (k={rep.k}) | {rep.hits}/{len(rep.results)} "
            f"| {rep.mrr:.2f} |"
        )
    for rep in reports:
        mode = "com filtro" if rep.filtered else "sem filtro"
        lines += ["", f"## {mode.capitalize()}", ""]
        lines += ["| Pergunta | Esperado | Posição | Recuperados |", "|---|---|---:|---|"]
        for r in rep.results:
            rank = str(r.rank) if r.rank else "—"
            lines.append(
                f"| {r.question.id} | `{r.question.expected_doc_id}` | {rank} "
                f"| {', '.join(f'`{d}`' for d in r.retrieved)} |"
            )
    return "\n".join(lines) + "\n"


async def main(k: int, report: Path | None) -> int:  # pragma: no cover - Postgres + Ollama
    from app.audit.db import create_engine, session_factory
    from app.config import get_settings
    from app.llm.ollama_client import OllamaClient
    from app.routing.cost import get_catalog
    from tools_mcp.kb import OllamaEmbedder, PostgresKBStore

    settings = get_settings()
    engine = create_engine(settings.database_url)
    embedder = OllamaEmbedder(
        OllamaClient(settings.ollama_base_url), get_catalog().get("ollama-embedding")
    )
    search = KnowledgeBaseSearch(embedder, PostgresKBStore(session_factory(engine)))
    questions = load_questions()
    try:
        reports = [await evaluate(search, questions, k=k, filtered=f) for f in (True, False)]
    finally:
        await engine.dispose()
    text = render(reports)
    print(text)
    if report:
        report.write_text(text, encoding="utf-8")
    return 0 if reports[0].hit_rate >= TARGET_HIT_RATE else 1


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.k, args.report)))
