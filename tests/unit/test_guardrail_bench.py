"""Benchmark do guardrail (T28): conjunto, métricas, retomada e relatório, sem modelo real."""

import re
from collections import Counter
from pathlib import Path

import pytest

from app.llm.base import LLMOutputError, LLMUnavailableError
from app.security.guardrail import GuardrailVerdict
from app.security.injection import scan
from evals import guardrail_bench as bench
from evals.guardrail_bench import BenchRow, GuardrailCase
from evals.labels import load_jsonl
from tests.graph.test_mvp import FakeLLM

pytestmark = pytest.mark.anyio

CLEAN = GuardrailVerdict(reason="ok", is_injection=False, is_spam=False, is_out_of_scope=False)
INJECTION = CLEAN.model_copy(update={"is_injection": True})


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def synthetic() -> list[GuardrailCase]:
    return load_jsonl(bench.SET_PATH, GuardrailCase)


def test_set_is_valid_balanced_and_free_of_personal_data() -> None:
    cases = synthetic()
    assert len({c.id for c in cases}) == len(cases)
    assert Counter(c.expected for c in cases) == {
        "injection": 22, "legit": 15, "spam": 8, "out_of_scope": 3,
    }  # fmt: skip
    for case in cases:
        case.to_lead_input()  # passa pela validação e sanitização do LeadInput
        text = f"{case.company_name} {case.contact_role} {case.message}"
        assert "@" not in text  # sem e-mail
        assert not re.search(r"\d{2}\s?9?\d{4}-?\d{4}", text)  # sem telefone
        for host in re.findall(r"https?://([\w.-]*\w)", text):
            assert host.endswith(".example.com"), host


def test_synthetic_attacks_get_past_the_rules_and_legit_cases_are_not_flagged() -> None:
    """O conjunto mede o que as regras não pegam: nenhum ataque sintético casa com elas."""
    for case in synthetic():
        hits = scan(f"{case.company_name}\n{case.contact_role}\n{case.message}")
        assert not hits, (case.id, hits)


def test_cases_add_the_dev_split_and_never_the_test_split() -> None:
    cases = bench.load_cases()
    dev = [c for c, _ in cases if c.id.startswith("L")]
    assert len(dev) == 20
    assert {c.id: c.expected for c in dev if c.expected != "legit"} == {
        "L005": "injection", "L020": "spam", "L029": "injection",
    }  # fmt: skip
    assert not {"L008", "L032", "L034", "L043"} & {c.id for c in dev}  # ataques do test


def test_model_spec_switches_the_slm_and_think_only_for_qwen() -> None:
    qwen, gemma = bench.model_spec("qwen3:1.7b"), bench.model_spec("gemma3:1b")
    assert (qwen.key, qwen.model, qwen.think) == ("ollama-slm", "qwen3:1.7b", False)
    assert (gemma.model, gemma.think) == ("gemma3:1b", None)
    assert bench.model_spec("groq-mini").provider == "groq"
    assert bench.runs_path("qwen3:1.7b").name == "guardrail-qwen3-1.7b.jsonl"


async def test_classify_retries_once_and_records_errors() -> None:
    case, lead = bench.load_cases()[0]
    spec = bench.model_spec("qwen3:1.7b")
    retried = await bench.classify(
        FakeLLM({GuardrailVerdict: [LLMOutputError("x"), INJECTION]}), spec, case, lead
    )
    assert retried.verdict == INJECTION and retried.attempts == 2 and retried.model_blocks
    down = await bench.classify(
        FakeLLM({GuardrailVerdict: [LLMUnavailableError("fora do ar")]}), spec, case, lead
    )
    assert down.verdict is None and down.error == "fora do ar" and not down.blocks
    bad = await bench.classify(
        FakeLLM({GuardrailVerdict: [LLMOutputError("x"), LLMOutputError("x")]}), spec, case, lead
    )
    assert bad.error == "saída fora do schema 2 vezes"


async def test_run_model_resumes_and_warms_up(tmp_path: Path) -> None:
    cases = bench.load_cases()[:3]
    out = tmp_path / "runs.jsonl"
    spec = bench.model_spec("qwen3:1.7b")
    first = FakeLLM({GuardrailVerdict: [CLEAN, CLEAN]})  # aquecimento + 1 caso
    await bench.run_model(first, spec, cases[:1], out)
    second = FakeLLM({GuardrailVerdict: [CLEAN, CLEAN, CLEAN]})
    rows = await bench.run_model(second, spec, cases, out)
    assert [r.id for r in rows] == [c.id for c, _ in cases[1:]]  # o 1º já estava gravado
    assert len(load_jsonl(out, BenchRow)) == 3
    assert len(second.calls[GuardrailVerdict]) == 3  # aquecimento + 2 casos


def row(case_id: str, expected: str, verdict: GuardrailVerdict | None, **kw: object) -> BenchRow:
    return BenchRow.model_validate(
        {
            "id": case_id,
            "model": "m",
            "expected": expected,
            "technique": "t",
            "rule_hit": False,
            "verdict": verdict,
            "latency_ms": 1000,
        }
        | kw
    )


def sample_rows() -> list[BenchRow]:
    spam = CLEAN.model_copy(update={"is_spam": True})
    oos = CLEAN.model_copy(update={"is_out_of_scope": True})
    return [
        *(row(f"I{i}", "injection", INJECTION) for i in range(9)),
        row("I9", "injection", CLEAN, rule_hit=True),  # só a regra pegou
        row("S1", "spam", spam),
        row("S2", "spam", None, error="fora do ar", latency_ms=0),
        row("N1", "legit", CLEAN),
        row("N2", "legit", INJECTION),
        row("O1", "out_of_scope", oos),
    ]


def test_stats_separate_model_from_rules_and_check_the_target() -> None:
    s = bench.stats("m", sample_rows())
    assert s.injections == (9, 10) and s.spam == (1, 2)
    assert s.combined == (11, 12)  # a regra soma o I9
    assert s.legit_blocked == (1, 2) and s.legit_ids == ("N2",)
    assert s.out_of_scope == (1, 1) and s.out_of_scope_blocked == 0
    assert s.errors == 1 and s.latency_p50 == 1000.0
    assert s.meets_target  # 90% e 1 legítimo bloqueado: no limite da meta
    worse = bench.stats("m", [*sample_rows(), row("N3", "legit", INJECTION)])
    assert not worse.meets_target


def test_report_lists_misses_per_model_and_rules_alone(tmp_path: Path) -> None:
    rows = sample_rows()
    text = bench.render([bench.stats("m", rows)], {"m": bench.wrong_rows(rows)}, rows)
    assert "| `m` | 9/10 (90%) | 1/2 (50%) | 11/12 (92%) | 1/2 (50%) |" in text
    assert "**Só as regras determinísticas:** 1/12 ataques e 0/2 legítimos" in text
    assert "| I9 | injection | t | injeção=False, spam=False, fora=False |" in text
    assert "| S2 | spam | t | erro: fora do ar |" in text
    assert "| N2 | legit |" in text and "| N1 |" not in text and "| O1 |" not in text


def test_report_reads_the_saved_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "RUNS_DIR", tmp_path)
    bench.runs_path("m").write_text(
        "".join(r.model_dump_json() + "\n" for r in sample_rows()), encoding="utf-8"
    )
    out = tmp_path / "report.md"
    text = bench.report(["m", "ausente"], out)
    assert out.read_text(encoding="utf-8").startswith("# Benchmark do guardrail")
    assert "`ausente`" not in text
    assert "| `m` (parcial: 15/68) |" in text and text.splitlines()[9].endswith("| — |")
    assert bench.main(["report", "m"]) == 0
